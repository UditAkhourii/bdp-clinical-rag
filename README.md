# Bidirectional Deterministic Pseudonymization for Clinical RAG

Reference implementation and reproducibility package for the preprint:

> **Retrieval Asymmetry in PHI-Tokenized Vector Stores: A Silent Failure Mode in Privacy-Preserving Clinical Retrieval-Augmented Generation**
> *Udit Raj Akhouri, Brane Labs* — medRxiv preprint, 2026.

## TL;DR

When a clinical RAG system masks patient identifiers in the user's query but not in the indexed corpus, two things break silently:

1. **Retrieval collapses.** The query embedding shifts away from the matching document embedding. On our synthetic ABDM-style Indian clinical corpus, recall@5 drops from **0.430 → 0.021** under the standard "read-only pseudonymization" pattern — a 95% relative drop with no exception raised.
2. **Privacy is still violated.** Because the indexed corpus is unmodified, the embedding API receives full raw PHI at ingest time. We measured **67.4%** of outbound payloads carrying real identifiers — the exact thing the deployment pattern was supposed to prevent.

We propose **Bidirectional Deterministic Pseudonymization (BDP)**: a symmetric write-and-read tokenization protocol with HMAC-keyed determinism and format-preserving decoders. On the same benchmark, BDP delivers **R@1 within 0.001 of the no-privacy baseline**, R@5 of 0.320, and **zero identifier leaks**. Clinical-accuracy grading with Gemini 2.5 Flash on a 30-query stratified subsample: BDP at 26.7% strict / 36.7% lenient vs. read-only at literal 0% across all categories.

The empirical core of the paper is a numerical-identity ablation: removing HMAC determinism from BDP collapses recall@5 to **exactly 0.018** — matching symmetric redaction. Read-only pseudonymization and randomized-token schemes are the same failure mode in different clothing.

## Headline results (bootstrap reproduction)

| Pipeline | R@5 | Clin. acc. (strict) | ID leak |
|---|---:|---:|---:|
| Raw (no privacy) | 0.430 | 0.333 | 100% |
| Symmetric redaction | 0.018 | 0.200 | 0% |
| **Read-only pseudonymization** | **0.021** | **0.000** | **67.4%** |
| **BDP (this work)** | **0.320** | **0.267** | **0%** |

20 patients × ~10 longitudinal notes × 100 queries; MiniLM-L6-v2 embeddings; Gemini 2.5 Flash as both generator and grader; deterministic seed 42. Regenerable byte-for-byte with one command (below).

## Repo layout

```
.
├── main.tex                     The manuscript (medRxiv-format LaTeX)
├── references.bib               20 real citations with verifiable URLs
├── MANUSCRIPT.md                Build instructions and status of the .tex
├── SUBMISSION.md                medRxiv field-by-field cheat sheet
├── figures/
│   ├── FIGURE_PROMPTS.md        Prompts for generating Figs 1, 2, 4
│   ├── render_fig3.py           Auto-renders Fig 3 from eval/results/results.json
│   └── fig3_recall.{pdf,png}    Committed rendered chart
└── eval/                        Python reference implementation + benchmark
    ├── bdp.py                   BDP protocol: HMAC tokens, format-preserving decoders, vault
    ├── corpus.py                Deterministic synthetic Indian clinical corpus generator
    ├── pipelines.py             Four pipelines (Raw / Redact / ReadOnly / BDP)
    ├── embed.py                 SBert (default) or OpenAI embeddings
    ├── run.py                   Retrieval benchmark (Table 2 in paper)
    ├── ablate.py                Ablation study (Table 3)
    ├── clinical_accuracy.py     LLM-graded answer correctness (Gemini / Anthropic / OpenAI)
    ├── smoke_test.py            Stdlib-only correctness check for the BDP module
    ├── requirements.txt
    ├── .env.example             Template for API keys (real keys in .env / .env.local)
    └── results/                 Committed eval outputs — the evidence the paper rests on
        ├── results.json         Retrieval benchmark
        ├── summary.md           Markdown table
        ├── ablation.json        Ablation study
        ├── ablation.md
        ├── clinical_accuracy.json
        └── clinical_accuracy.md
```

## Reproduce in five minutes

Requirements: Python 3.10+, ~2 GB disk (for sentence-transformers model).

```powershell
git clone https://github.com/UditAkhourii/bdp-clinical-rag.git
cd bdp-clinical-rag/eval
python -m pip install -r requirements.txt
python -m corpus           # ~1 s, deterministic from SEED=42
python -m run              # ~30 s first run (downloads MiniLM), then ~10 s
python -m ablate           # ~10 s

# Outputs land in results/ and match the committed files byte-for-byte.
```

For clinical-accuracy grading (optional, needs a Gemini API key):

```powershell
copy .env.example .env.local
# edit .env.local, set GEMINI_API_KEY=...
python -m clinical_accuracy --backend gemini --n 30
```

Free Gemini API key at <https://aistudio.google.com/app/apikey>. The `gemini-2.5-flash` default is well within free-tier limits for n=100.

## Scaling to the paper's target corpus

Bootstrap = 20 patients / 207 notes / 100 queries; runs on CPU with no API key. Full paper-scale = 1,000 patients / 10,000 notes / 5,000 queries with `text-embedding-3-large`. To switch, edit `eval/config.py`:

```python
SCALE = PAPER_SCALE
EMBED_BACKEND = "openai"   # set OPENAI_API_KEY first
```

Expected cost: ~$30–80 OpenAI spend, ~2–4 h wall time.

## What this paper is and is not

**Is:** a problem-identification + protocol-proposal paper. First to formalize the write/read normalization mismatch as a failure-mode class for clinical RAG; first public BDP specification with reproducible benchmark; first synthetic ABDM-style Indian clinical eval corpus.

**Is not:** a benchmark-leaderboard paper. We do not claim better embeddings than `text-embedding-3-large`, better DP guarantees than Koga et al. 2024, or smaller models than anyone. The contribution is conceptual clarity + empirical demonstration + a working reference implementation.

## License

- **Code:** MIT (see `LICENSE`)
- **Synthetic corpus:** generator deterministic from `SEED=42`. The notes, queries, and identifier roster generated by `python -m corpus` are CC-BY-4.0; you may reuse and redistribute with attribution.
- **Manuscript:** CC-BY-4.0 once posted to medRxiv.

## Citation

Once the preprint is live a DOI will appear here. Until then:

```bibtex
@article{akhouri2026bdp,
  author  = {Akhouri, Udit Raj},
  title   = {Retrieval Asymmetry in {PHI}-Tokenized Vector Stores: A Silent Failure Mode in Privacy-Preserving Clinical Retrieval-Augmented Generation},
  journal = {medRxiv preprint},
  year    = {2026},
  note    = {Forthcoming}
}
```

## Contact

Udit Raj Akhouri — Lead Researcher, Brane Labs — <udit@branelabs.org>

Issues and pull requests welcome.
