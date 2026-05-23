"""
BDP ablation study (paper Table 2).

Three variants strip one component of BDP at a time:

  bdp_no_format    : tokens are hex hashes (TOK_a1b2c3d4) -- no name-shaped,
                     phone-shaped, date-shaped surface form. Tests whether
                     format preservation actually buys us retrieval signal.

  bdp_no_category  : all identifier categories use the same decoder (NAME).
                     A phone gets mapped to a name; a pincode gets mapped to a
                     name. Tests whether per-category format-preserving
                     decoders matter, vs a single decoder that at least keeps
                     the token bag stable.

  bdp_no_hmac      : tokens are random per call (no key, no cache, no vault).
                     phi_w and phi_r are independent random functions. This
                     re-creates retrieval asymmetry through non-determinism
                     instead of through write/read mismatch. Expected to
                     collapse to redact-level recall.

  python -m ablate
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
from pathlib import Path

from config import RESULTS_DIR, TOP_K, EMBED_BACKEND
from bdp import (
    DECODERS, LookupDetector, Vault,
    decode_name, tokenize_text,
)
from pipelines import BDPPipeline, IndexedNote
from run import (
    load_corpus, recall_at_k, reciprocal_rank, leakage_rate,
)


# ---------------------------------------------------------------------------
# Ablation #1 -- no format preservation
# ---------------------------------------------------------------------------

def _decoder_hex(category: str):
    """Returns a decoder that emits TOK_<8hex> regardless of category."""
    def decode(value: str) -> str:
        h = hashlib.sha256(f"{category}||{value}".encode()).hexdigest()[:8]
        return f"TOK_{h}"
    return decode


class BDPNoFormatPipeline(BDPPipeline):
    name = "bdp_no_format"

    def _phi(self, text: str) -> str:
        # Local DECODERS swap, restore after
        saved = dict(DECODERS)
        try:
            for c in DECODERS:
                DECODERS[c] = _decoder_hex(c)
            return tokenize_text(text, self.detector, vault=self.vault)
        finally:
            DECODERS.clear()
            DECODERS.update(saved)

    def phi_w(self, text: str) -> str: return self._phi(text)
    def phi_r(self, text: str) -> str: return self._phi(text)


# ---------------------------------------------------------------------------
# Ablation #2 -- no category awareness (single decoder for all categories)
# ---------------------------------------------------------------------------

class BDPNoCategoryPipeline(BDPPipeline):
    name = "bdp_no_category"

    def _phi(self, text: str) -> str:
        saved = dict(DECODERS)
        try:
            for c in DECODERS:
                DECODERS[c] = decode_name   # name decoder for everything
            return tokenize_text(text, self.detector, vault=self.vault)
        finally:
            DECODERS.clear()
            DECODERS.update(saved)

    def phi_w(self, text: str) -> str: return self._phi(text)
    def phi_r(self, text: str) -> str: return self._phi(text)


# ---------------------------------------------------------------------------
# Ablation #3 -- no HMAC determinism (random tokens per call, no cache)
# ---------------------------------------------------------------------------

def _decoder_random(category: str):
    def decode(value: str) -> str:
        return f"TOK_{secrets.token_hex(4)}"
    return decode


class BDPNoHmacPipeline(BDPPipeline):
    name = "bdp_no_hmac"

    def _phi(self, text: str) -> str:
        # Bypass the vault entirely so each call gets fresh randomness
        saved = dict(DECODERS)
        try:
            for c in DECODERS:
                DECODERS[c] = _decoder_random(c)
            # vault=None -> tokens are not memoized; calling twice yields different output
            return tokenize_text(text, self.detector, vault=None)
        finally:
            DECODERS.clear()
            DECODERS.update(saved)

    def phi_w(self, text: str) -> str: return self._phi(text)
    def phi_r(self, text: str) -> str: return self._phi(text)


# ---------------------------------------------------------------------------
# Runner (mirrors run.py::run_pipeline but parameterizes the class)
# ---------------------------------------------------------------------------

def run_variant(cls, notes, queries, detector, identifier_values):
    pipe = cls(detector)
    indexed = [IndexedNote(note_id=n["note_id"], text=n["text"]) for n in notes]
    pipe.index(indexed)

    per_q = []
    for q in queries:
        retrieved = pipe.query(q["text"], k=max(TOP_K))
        per_q.append({
            "rr": reciprocal_rank(retrieved, q["ground_truth_note_ids"]),
            **{f"r@{k}": recall_at_k(retrieved, q["ground_truth_note_ids"], k) for k in TOP_K},
        })

    def _mean(xs): return sum(xs) / len(xs) if xs else 0.0
    summary = {
        "variant": cls.name,
        "overall": {
            "mrr": round(_mean([r["rr"] for r in per_q]), 4),
            **{f"r@{k}": round(_mean([r[f"r@{k}"] for r in per_q]), 4) for k in TOP_K},
        },
        "leakage_rate": round(leakage_rate(pipe.outbound_payloads, identifier_values), 4),
    }
    print(f"[ablate] {cls.name:18s} R@5={summary['overall']['r@5']:.3f} "
          f"MRR={summary['overall']['mrr']:.3f} leak={summary['leakage_rate']:.3f}")
    return summary


def render_markdown(rows: list[dict], baseline_bdp: dict | None) -> str:
    out = [
        "# BDP Ablation Study\n",
        f"Embedder: `{EMBED_BACKEND}`. Same corpus and queries as `summary.md`.\n",
        "| Variant | R@1 | R@5 | R@10 | MRR | ID leak | $\\Delta$ R@5 vs BDP |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    bdp_r5 = baseline_bdp["overall"]["r@5"] if baseline_bdp else None
    if baseline_bdp:
        o = baseline_bdp["overall"]
        out.append(
            f"| **bdp (full)** | {o['r@1']:.3f} | {o['r@5']:.3f} | {o['r@10']:.3f} "
            f"| {o['mrr']:.3f} | {baseline_bdp['leakage_rate']:.3f} | --- |"
        )
    for r in rows:
        o = r["overall"]
        delta = f"{o['r@5'] - bdp_r5:+.3f}" if bdp_r5 is not None else "n/a"
        out.append(
            f"| {r['variant']} | {o['r@1']:.3f} | {o['r@5']:.3f} | {o['r@10']:.3f} "
            f"| {o['mrr']:.3f} | {r['leakage_rate']:.3f} | {delta} |"
        )
    return "\n".join(out) + "\n"


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    _, notes, queries, roster = load_corpus()
    detector = LookupDetector([(c, v) for c, v in roster])
    identifier_values = [v for _, v in roster if v]

    # Load full-BDP baseline from results/results.json for the delta column
    baseline_bdp = None
    res_path = RESULTS_DIR / "results.json"
    if res_path.exists():
        for entry in json.loads(res_path.read_text()):
            if entry.get("pipeline") == "bdp":
                baseline_bdp = entry
                break

    rows = [
        run_variant(BDPNoFormatPipeline,   notes, queries, detector, identifier_values),
        run_variant(BDPNoCategoryPipeline, notes, queries, detector, identifier_values),
        run_variant(BDPNoHmacPipeline,     notes, queries, detector, identifier_values),
    ]

    (RESULTS_DIR / "ablation.json").write_text(json.dumps(rows, indent=2))
    (RESULTS_DIR / "ablation.md").write_text(render_markdown(rows, baseline_bdp))
    print(f"\n[ablate] wrote {RESULTS_DIR/'ablation.json'} and {RESULTS_DIR/'ablation.md'}")


if __name__ == "__main__":
    main()
