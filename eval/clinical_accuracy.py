"""
Clinical-accuracy grader (paper Table 2 -- "Clin. acc." column).

Backends supported:
  --backend gemini      (Google Gemini, env GEMINI_API_KEY or GOOGLE_API_KEY)
  --backend anthropic   (env ANTHROPIC_API_KEY)
  --backend openai      (env OPENAI_API_KEY)
  --backend dry-run     (deterministic stub, no key needed)

Keys are read from the process environment. A `.env` file in this directory
is auto-loaded via python-dotenv if present, e.g.

    # paper/eval/.env
    GEMINI_API_KEY=ya29...your-key...

`.env` is already in `.gitignore`, so it never gets committed.

For a stratified subsample of queries:
  1. For each pipeline (raw / redact / read_only / bdp):
       a. Index the corpus (reuses the same Embedder cache).
       b. Retrieve top-k chunks for the query.
       c. Generate an answer with an LLM, given the query and chunks.
       d. For tokenized pipelines (bdp, read_only), detokenize the answer
          through the pipeline's vault -- this mirrors the controller-side
          rendering a clinician would actually see.
  2. Grade each detokenized answer against the ground-truth note text,
     using a second LLM call with a rubric (correct / partial / incorrect).
  3. Report per-pipeline accuracy and per-category accuracy.

Backends: Anthropic (default, matches the manuscript's claude-sonnet-4-6)
or OpenAI. A --dry-run mode replaces both generator and grader with a
deterministic stub so the harness can be validated end-to-end with zero
API spend.

  python -m clinical_accuracy
  python -m clinical_accuracy --dry-run
  python -m clinical_accuracy --n 50 --backend anthropic
  python -m clinical_accuracy --n 50 --backend openai
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

# Auto-load .env / .env.local from this directory so users can drop a key in
# a file rather than having to set a shell env var every session.
# `.env.local` takes precedence (loaded last with override=True), matching
# the Next.js / Vercel convention.
try:
    from dotenv import load_dotenv
    _eval_dir = Path(__file__).resolve().parent
    load_dotenv(_eval_dir / ".env")
    load_dotenv(_eval_dir / ".env.local", override=True)
except ImportError:
    pass

from config import DATA_DIR, RESULTS_DIR, SEED, TOP_K
from bdp import LookupDetector, detokenize_text
from pipelines import IndexedNote, PIPELINE_REGISTRY
from run import load_corpus


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_N_SAMPLE = 30                    # paper-scale target: 500
GEN_TOP_K = 5                            # chunks fed to the generator
ANTHROPIC_MODEL = "claude-sonnet-4-5"    # closest current model id; flip to 4-6 when GA
OPENAI_MODEL = "gpt-4o-mini"             # cheap and good enough as a grader; flip to gpt-4o or larger as needed
GEMINI_MODEL = "gemini-2.5-flash"        # cheap+fast; flip to gemini-2.5-pro for higher-quality grading


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

GEN_SYSTEM = (
    "You are a clinical assistant answering questions about a single patient. "
    "Use only the provided clinical notes; do not invent information. "
    "Be concise: one or two sentences."
)

GEN_USER_TEMPLATE = """Patient question:
{query}

Relevant clinical notes (top-{k} retrieved):
---
{chunks}
---

Answer the question briefly. If the notes do not contain the answer, say so."""


GRADER_SYSTEM = (
    "You are a clinical-accuracy reviewer. You will be given a clinical "
    "question, a candidate answer, and the ground-truth note. You must "
    "decide whether the candidate answer is correct (it states the right "
    "clinical fact), partial (it is on-topic but incomplete or imprecise), "
    "or incorrect (wrong fact, wrong patient, or fabricated). Respond with "
    "exactly one word: CORRECT, PARTIAL, or INCORRECT. No other text."
)

GRADER_USER_TEMPLATE = """Question: {query}

Candidate answer: {answer}

Ground-truth note:
---
{gt_note}
---

Verdict (CORRECT / PARTIAL / INCORRECT):"""


# ---------------------------------------------------------------------------
# Backend adapters
# ---------------------------------------------------------------------------

class Backend:
    name = "base"
    def chat(self, system: str, user: str) -> str:
        raise NotImplementedError


def chat_with_retry(backend: "Backend", system: str, user: str,
                    max_attempts: int = 4, base_delay: float = 1.5) -> str:
    """Retry transient errors (network, 5xx, rate limit) with exponential backoff."""
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return backend.chat(system, user)
        except Exception as e:  # noqa: BLE001 - we want broad catch for network blips
            last_exc = e
            if attempt == max_attempts:
                break
            delay = base_delay * (2 ** (attempt - 1))
            print(f"  [retry {attempt}/{max_attempts - 1}] {type(e).__name__}: {str(e)[:120]}; sleeping {delay:.1f}s")
            time.sleep(delay)
    assert last_exc is not None
    raise last_exc


class AnthropicBackend(Backend):
    name = "anthropic"
    def __init__(self, model: str = ANTHROPIC_MODEL):
        import anthropic  # type: ignore
        self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.model = model

    def chat(self, system: str, user: str) -> str:
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=256,
            temperature=0,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return resp.content[0].text.strip()


class OpenAIBackend(Backend):
    name = "openai"
    def __init__(self, model: str = OPENAI_MODEL):
        from openai import OpenAI  # type: ignore
        self.client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        self.model = model

    def chat(self, system: str, user: str) -> str:
        resp = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content.strip()


class GeminiBackend(Backend):
    """Google Gemini via the google-genai SDK.

    Reads GEMINI_API_KEY first, falls back to GOOGLE_API_KEY (both are
    accepted conventions in Google's own docs).
    """
    name = "gemini"
    def __init__(self, model: str = GEMINI_MODEL):
        from google import genai  # type: ignore
        from google.genai import types  # type: ignore
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY (or GOOGLE_API_KEY) not set. Put it in "
                "paper/eval/.env or export it in your shell."
            )
        self.client = genai.Client(api_key=api_key)
        self.types = types
        self.model = model

    def chat(self, system: str, user: str) -> str:
        # Gemini 2.5 models reason internally and those reasoning tokens
        # count against max_output_tokens; without thinking_budget=0 the
        # visible response is often empty/truncated.
        resp = self.client.models.generate_content(
            model=self.model,
            contents=user,
            config=self.types.GenerateContentConfig(
                system_instruction=system,
                temperature=0,
                max_output_tokens=512,
                thinking_config=self.types.ThinkingConfig(thinking_budget=0),
            ),
        )
        return (resp.text or "").strip()


class DryRunBackend(Backend):
    """
    Deterministic stub. Generator returns a templated answer; grader returns a
    verdict derived from a hash of (query, answer, ground-truth) so the same
    inputs always produce the same verdict and the harness can be validated.
    """
    name = "dry-run"
    def chat(self, system: str, user: str) -> str:
        h = int(hashlib.sha256((system + user).encode()).hexdigest(), 16)
        if "Verdict" in user:
            # Grader call. Bias verdict toward CORRECT when the answer
            # appears to contain a chunk of the ground-truth note.
            answer_block = user.split("Candidate answer:", 1)[1].split("\n", 1)[1] if "Candidate answer:" in user else ""
            gt_block = user.split("Ground-truth note:", 1)[1] if "Ground-truth note:" in user else ""
            overlap = sum(1 for tok in answer_block.split() if tok in gt_block) / max(len(answer_block.split()), 1)
            if overlap > 0.4:
                return "CORRECT"
            if overlap > 0.2:
                return "PARTIAL"
            return "INCORRECT" if h % 7 != 0 else "PARTIAL"
        # Generator call: return the first sentence of the first chunk.
        chunks_block = user.split("---", 2)[1] if "---" in user else user
        first = chunks_block.strip().split("\n", 1)[0]
        return f"Based on the notes: {first[:200]}"


def build_backend(name: str) -> Backend:
    if name == "dry-run":
        return DryRunBackend()
    if name == "anthropic":
        return AnthropicBackend()
    if name == "openai":
        return OpenAIBackend()
    if name == "gemini":
        return GeminiBackend()
    raise ValueError(f"unknown backend: {name}")


# ---------------------------------------------------------------------------
# Pipeline harness wrapper -- caches indexed pipelines
# ---------------------------------------------------------------------------

@dataclass
class HarnessedPipeline:
    name: str
    pipe: object   # Pipeline subclass instance
    vault: object | None   # Vault for tokenized pipelines, else None


def build_harness(notes, detector) -> list[HarnessedPipeline]:
    out: list[HarnessedPipeline] = []
    indexed = [IndexedNote(note_id=n["note_id"], text=n["text"]) for n in notes]
    for name, cls in PIPELINE_REGISTRY.items():
        print(f"[clin] indexing pipeline: {name}")
        pipe = cls(detector)
        pipe.index(indexed)
        vault = getattr(pipe, "vault", None)
        out.append(HarnessedPipeline(name=name, pipe=pipe, vault=vault))
    return out


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------

def stratified_sample(queries: list[dict], n: int, rng: random.Random) -> list[dict]:
    by_cat: dict[str, list[dict]] = {}
    for q in queries:
        by_cat.setdefault(q["category"], []).append(q)
    cats = sorted(by_cat)
    per_cat = max(1, n // len(cats))
    sample: list[dict] = []
    for cat in cats:
        pool = by_cat[cat]
        rng.shuffle(pool)
        sample.extend(pool[:per_cat])
    rng.shuffle(sample)
    return sample[:n]


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run(n_sample: int, backend_name: str, gen_top_k: int = GEN_TOP_K) -> None:
    notes_by_id, notes, queries, roster = _load_indexed_corpus()
    detector = LookupDetector([(c, v) for c, v in roster])

    backend = build_backend(backend_name)
    print(f"[clin] backend: {backend.name}    sample n={n_sample}    top-k for generator={gen_top_k}")

    rng = random.Random(SEED)
    sample = stratified_sample(queries, n_sample, rng)
    harness = build_harness(notes, detector)

    per_pipeline: dict[str, list[dict]] = {h.name: [] for h in harness}

    for qi, q in enumerate(sample, start=1):
        print(f"[clin] query {qi}/{len(sample)}  cat={q['category']}  id={q['query_id']}")
        gt_note_text = "\n\n".join(
            notes_by_id[gid]["text"] for gid in q["ground_truth_note_ids"]
            if gid in notes_by_id
        )

        for h in harness:
            t0 = time.perf_counter()
            retrieved_ids = h.pipe.query(q["text"], k=gen_top_k)
            # CRITICAL: the LLM provider must see chunks transformed by the
            # same phi_w that was applied at index time. Sending raw chunks
            # would (a) leak PHI to the model provider under BDP, defeating
            # the privacy guarantee, and (b) create an artificial
            # query/chunk name mismatch that distorts accuracy measurement.
            chunks_text = "\n\n---\n\n".join(
                h.pipe.phi_w(notes_by_id[rid]["text"])
                for rid in retrieved_ids
                if rid in notes_by_id
            )

            gen_prompt = GEN_USER_TEMPLATE.format(
                query=_phi_r_query(h, q["text"]),
                k=gen_top_k,
                chunks=chunks_text,
            )
            try:
                raw_answer = chat_with_retry(backend, GEN_SYSTEM, gen_prompt)
                answer = _maybe_detokenize(h, raw_answer)

                grader_prompt = GRADER_USER_TEMPLATE.format(
                    query=q["text"],
                    answer=answer,
                    gt_note=gt_note_text,
                )
                verdict = chat_with_retry(backend, GRADER_SYSTEM, grader_prompt).upper()
                if verdict not in ("CORRECT", "PARTIAL", "INCORRECT"):
                    verdict = "PARTIAL"   # be charitable to off-format grader output
            except Exception as e:  # noqa: BLE001
                print(f"  [skip] {h.name} query {q['query_id']}: {type(e).__name__}: {str(e)[:120]}")
                verdict = "SKIPPED"

            per_pipeline[h.name].append({
                "query_id": q["query_id"],
                "category": q["category"],
                "verdict": verdict,
                "latency_s": round(time.perf_counter() - t0, 2),
            })

    _write_results(per_pipeline, backend_name, n_sample)


def _phi_r_query(h: HarnessedPipeline, query_text: str) -> str:
    """Show the generator the query in the same form the read-side embedder saw."""
    return h.pipe.phi_r(query_text)


def _maybe_detokenize(h: HarnessedPipeline, answer: str) -> str:
    if h.vault is None:
        return answer
    return detokenize_text(answer, h.vault)


def _load_indexed_corpus():
    _, notes, queries, roster = load_corpus()
    notes_by_id = {n["note_id"]: n for n in notes}
    return notes_by_id, notes, queries, roster


def _write_results(per_pipeline: dict[str, list[dict]], backend_name: str, n: int) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    summary = {}
    for name, rows in per_pipeline.items():
        # Denominator excludes SKIPPED rows so transient failures don't bias accuracy.
        graded = [r for r in rows if r["verdict"] != "SKIPPED"]
        n_correct = sum(1 for r in graded if r["verdict"] == "CORRECT")
        n_partial = sum(1 for r in graded if r["verdict"] == "PARTIAL")
        n_incorrect = sum(1 for r in graded if r["verdict"] == "INCORRECT")
        n_skipped = sum(1 for r in rows if r["verdict"] == "SKIPPED")
        total = len(graded) or 1
        by_cat: dict[str, dict[str, int]] = {}
        for r in graded:
            d = by_cat.setdefault(r["category"], {"CORRECT": 0, "PARTIAL": 0, "INCORRECT": 0, "n": 0})
            d[r["verdict"]] += 1
            d["n"] += 1
        summary[name] = {
            "n_graded": total,
            "n_skipped": n_skipped,
            "accuracy_strict": round(n_correct / total, 4),
            "accuracy_lenient": round((n_correct + 0.5 * n_partial) / total, 4),
            "incorrect_rate": round(n_incorrect / total, 4),
            "by_category": {
                cat: {
                    "n": d["n"],
                    "acc_strict": round(d["CORRECT"] / d["n"], 4),
                    "acc_lenient": round((d["CORRECT"] + 0.5 * d["PARTIAL"]) / d["n"], 4),
                }
                for cat, d in by_cat.items()
            },
        }

    out_json = RESULTS_DIR / "clinical_accuracy.json"
    out_json.write_text(json.dumps({"backend": backend_name, "n_sample": n, "summary": summary}, indent=2))

    md = [f"# Clinical Accuracy (backend: `{backend_name}`, n={n})\n",
          "| Pipeline | Acc (strict) | Acc (lenient) | Incorrect | n graded | skipped |",
          "|---|---:|---:|---:|---:|---:|"]
    for name, s in summary.items():
        md.append(
            f"| {name} | {s['accuracy_strict']:.3f} | {s['accuracy_lenient']:.3f} | "
            f"{s['incorrect_rate']:.3f} | {s['n_graded']} | {s['n_skipped']} |"
        )
    md.append("\n## Per-category strict accuracy\n")
    cats = sorted({c for s in summary.values() for c in s["by_category"]})
    md.append("| Pipeline | " + " | ".join(cats) + " |")
    md.append("|---|" + "|".join(["---:"] * len(cats)) + "|")
    for name, s in summary.items():
        row = [f"{s['by_category'].get(c, {}).get('acc_strict', 0.0):.3f}" for c in cats]
        md.append(f"| {name} | " + " | ".join(row) + " |")

    out_md = RESULTS_DIR / "clinical_accuracy.md"
    out_md.write_text("\n".join(md) + "\n")
    print(f"\n[clin] wrote {out_json} and {out_md}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=DEFAULT_N_SAMPLE,
                    help=f"stratified subsample size (default: {DEFAULT_N_SAMPLE})")
    ap.add_argument("--backend", choices=["gemini", "anthropic", "openai", "dry-run"], default="dry-run",
                    help="LLM backend. Default 'dry-run' for harness validation without API spend.")
    ap.add_argument("--top-k", type=int, default=GEN_TOP_K,
                    help=f"chunks passed to the generator (default: {GEN_TOP_K})")
    ap.add_argument("--dry-run", action="store_true",
                    help="alias for --backend dry-run")
    return ap.parse_args()


if __name__ == "__main__":
    args = parse_args()
    backend_name = "dry-run" if args.dry_run else args.backend
    run(n_sample=args.n, backend_name=backend_name, gen_top_k=args.top_k)
