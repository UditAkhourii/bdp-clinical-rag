"""
Render Figure 3 from real eval data.

Reads ../eval/results/results.json and writes fig3_recall.pdf + .png in this
directory. Grouped bar chart: four pipelines on the x-axis, three R@k bars
per pipeline.

  cd D:\\Projects\\brane-mvp\\paper\\figures
  python render_fig3.py
"""
from __future__ import annotations
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent / "eval" / "results" / "results.json"
OUT_PDF = HERE / "fig3_recall.pdf"
OUT_PNG = HERE / "fig3_recall.png"

PIPELINE_ORDER = ["raw", "redact", "read_only", "bdp"]
PIPELINE_LABELS = {
    "raw": "Raw",
    "redact": "Redaction",
    "read_only": "Read-only",
    "bdp": "BDP",
}
KS = [1, 5, 10]
# Colorblind-friendly: BDP in teal, others in grays
PALETTE = {1: "#7f7f7f", 5: "#4f4f4f", 10: "#1f1f1f"}


def main() -> None:
    data = json.loads(RESULTS.read_text())
    by_name = {row["pipeline"]: row for row in data}

    n_pipes = len(PIPELINE_ORDER)
    n_ks = len(KS)
    bar_w = 0.25
    x = np.arange(n_pipes)

    fig, ax = plt.subplots(figsize=(7.5, 4.2), dpi=160)
    for i, k in enumerate(KS):
        vals = [by_name[p]["overall"][f"r@{k}"] for p in PIPELINE_ORDER]
        offset = (i - (n_ks - 1) / 2) * bar_w
        bars = ax.bar(x + offset, vals, bar_w, label=f"R@{k}", color=PALETTE[k],
                      edgecolor="white", linewidth=0.5)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.012, f"{v:.3f}",
                    ha="center", va="bottom", fontsize=7.5)

    # Highlight BDP column with a teal background band
    bdp_idx = PIPELINE_ORDER.index("bdp")
    ax.axvspan(bdp_idx - 0.45, bdp_idx + 0.45, color="#5fb3a6", alpha=0.10, zorder=0)

    ax.set_xticks(x)
    ax.set_xticklabels([PIPELINE_LABELS[p] for p in PIPELINE_ORDER])
    ax.set_ylabel("Recall@k")
    ax.set_ylim(0, max(1.0, max(by_name[p]["overall"]["r@10"] for p in PIPELINE_ORDER) * 1.15))
    ax.set_title("Retrieval recall across pipelines (bootstrap reproduction, n=100)", fontsize=11)
    ax.legend(loc="upper right", frameon=False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.yaxis.grid(True, alpha=0.25, linestyle="--", linewidth=0.5)
    ax.set_axisbelow(True)

    plt.tight_layout()
    fig.savefig(OUT_PDF, bbox_inches="tight")
    fig.savefig(OUT_PNG, bbox_inches="tight")
    print(f"[fig3] wrote {OUT_PDF}")
    print(f"[fig3] wrote {OUT_PNG}")


if __name__ == "__main__":
    main()
