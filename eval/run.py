"""
End-to-end benchmark runner.

  python -m run

Steps:
  1. Load (or build) corpus from data/.
  2. For each pipeline in config.PIPELINES:
       a. Index all notes (records outbound payloads at write time).
       b. Run every query, collect top-k retrieved note ids.
       c. Compute recall@k, MRR, identifier-leakage rate.
  3. Write results/results.json (machine-readable) and results/summary.md
     (paste-into-paper-friendly).

This is the artifact the manuscript's Table 1 + Figure 3 are generated from.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from config import DATA_DIR, RESULTS_DIR, TOP_K, PIPELINES, EMBED_BACKEND
from bdp import LookupDetector
from pipelines import IndexedNote, PIPELINE_REGISTRY


# ---------------------------------------------------------------------------
# Load corpus
# ---------------------------------------------------------------------------

def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_corpus():
    patients_p = DATA_DIR / "patients.jsonl"
    notes_p = DATA_DIR / "notes.jsonl"
    queries_p = DATA_DIR / "queries.jsonl"
    roster_p = DATA_DIR / "roster.json"

    if not (patients_p.exists() and notes_p.exists() and queries_p.exists()):
        print("[run] corpus missing -- generating with corpus.main() first")
        from corpus import main as build
        build()

    patients = _read_jsonl(patients_p)
    notes = _read_jsonl(notes_p)
    queries = _read_jsonl(queries_p)
    roster = json.loads(roster_p.read_text(encoding="utf-8"))
    return patients, notes, queries, roster


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def recall_at_k(retrieved: list[str], gt: list[str], k: int) -> float:
    if not gt:
        return 0.0
    top = set(retrieved[:k])
    hits = sum(1 for g in gt if g in top)
    return hits / len(gt)


def reciprocal_rank(retrieved: list[str], gt: list[str]) -> float:
    gt_set = set(gt)
    for i, rid in enumerate(retrieved, start=1):
        if rid in gt_set:
            return 1.0 / i
    return 0.0


def leakage_rate(payloads: list[str], identifier_values: list[str]) -> float:
    """Fraction of outbound payloads that contain >=1 raw identifier value."""
    if not payloads:
        return 0.0
    leaked = 0
    for p in payloads:
        for v in identifier_values:
            if v and v in p:
                leaked += 1
                break
    return leaked / len(payloads)


# ---------------------------------------------------------------------------
# Per-pipeline run
# ---------------------------------------------------------------------------

def run_pipeline(name: str, notes, queries, detector, identifier_values):
    print(f"\n[run] === pipeline: {name} ===")
    t0 = time.perf_counter()

    pipe = PIPELINE_REGISTRY[name](detector)
    indexed = [IndexedNote(note_id=n["note_id"], text=n["text"]) for n in notes]
    pipe.index(indexed)
    t_index = time.perf_counter() - t0
    print(f"[run] indexed {len(indexed)} notes in {t_index:.1f}s")

    per_q = []
    by_cat: dict[str, list[dict]] = {}
    for q in queries:
        retrieved = pipe.query(q["text"], k=max(TOP_K))
        row = {
            "query_id": q["query_id"],
            "category": q["category"],
            "rr": reciprocal_rank(retrieved, q["ground_truth_note_ids"]),
            **{f"r@{k}": recall_at_k(retrieved, q["ground_truth_note_ids"], k) for k in TOP_K},
        }
        per_q.append(row)
        by_cat.setdefault(q["category"], []).append(row)

    def _mean(xs):
        return sum(xs) / len(xs) if xs else 0.0

    summary = {
        "pipeline": name,
        "n_notes": len(notes),
        "n_queries": len(queries),
        "index_seconds": round(t_index, 2),
        "overall": {
            "mrr": round(_mean([r["rr"] for r in per_q]), 4),
            **{f"r@{k}": round(_mean([r[f"r@{k}"] for r in per_q]), 4) for k in TOP_K},
        },
        "by_category": {
            cat: {
                "n": len(rows),
                "mrr": round(_mean([r["rr"] for r in rows]), 4),
                **{f"r@{k}": round(_mean([r[f"r@{k}"] for r in rows]), 4) for k in TOP_K},
            }
            for cat, rows in by_cat.items()
        },
        "leakage_rate": round(
            leakage_rate(pipe.outbound_payloads, identifier_values), 4
        ),
        "outbound_payload_count": len(pipe.outbound_payloads),
    }
    print(f"[run] {name}: recall@5={summary['overall']['r@5']:.3f} "
          f"MRR={summary['overall']['mrr']:.3f} "
          f"leak={summary['leakage_rate']:.3f}")
    return summary


# ---------------------------------------------------------------------------
# Markdown summary (drops into the paper)
# ---------------------------------------------------------------------------

def render_markdown(results: list[dict]) -> str:
    head = (
        f"# BDP Eval -- bootstrap run\n\n"
        f"Embedder: `{EMBED_BACKEND}`\n\n"
        f"| Pipeline | R@1 | R@5 | R@10 | MRR | ID leak |\n"
        f"|---|---:|---:|---:|---:|---:|\n"
    )
    rows = []
    for r in results:
        o = r["overall"]
        rows.append(
            f"| {r['pipeline']} | {o['r@1']:.3f} | {o['r@5']:.3f} | "
            f"{o['r@10']:.3f} | {o['mrr']:.3f} | {r['leakage_rate']:.3f} |"
        )
    tail = "\n\n## Recall@5 by query category\n\n"
    cats = sorted({c for r in results for c in r["by_category"]})
    tail += "| Pipeline | " + " | ".join(cats) + " |\n"
    tail += "|---|" + "|".join(["---:"] * len(cats)) + "|\n"
    for r in results:
        cells = [f"{r['by_category'].get(c, {}).get('r@5', 0.0):.3f}" for c in cats]
        tail += f"| {r['pipeline']} | " + " | ".join(cells) + " |\n"
    return head + "\n".join(rows) + tail


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    _, notes, queries, roster = load_corpus()

    detector = LookupDetector([(c, v) for c, v in roster])
    identifier_values = [v for _, v in roster if v]

    results = [
        run_pipeline(name, notes, queries, detector, identifier_values)
        for name in PIPELINES
    ]

    out_json = RESULTS_DIR / "results.json"
    out_json.write_text(json.dumps(results, indent=2))
    out_md = RESULTS_DIR / "summary.md"
    out_md.write_text(render_markdown(results))

    print(f"\n[run] wrote {out_json} and {out_md}")


if __name__ == "__main__":
    main()
