# BDP Eval Harness

Reference implementation of **Bidirectional Deterministic Pseudonymization** plus the four-pipeline retrieval benchmark from the manuscript at `../main.tex`.

## What's here

```
paper/eval/
  config.py          # scale, seeds, embedder choice
  bdp.py             # BDP reference impl: tokenize / detokenize / vault / detector / redact baseline
  corpus.py          # synthetic Indian-clinical corpus generator (deterministic from SEED)
  embed.py           # SBert (default) / OpenAI embedder + in-memory cosine store
  pipelines.py       # Raw / Redact / ReadOnly / BDP -- the four pipelines
  run.py             # end-to-end benchmark: writes results/results.json + summary.md
  smoke_test.py      # stdlib-only sanity test for the BDP module
  requirements.txt
```

## Setup

This repo has no Python interpreter installed. Pick one:

**Option A — uv (recommended, fastest)**
```powershell
# Install uv (one-shot, no admin)
irm https://astral.sh/uv/install.ps1 | iex
# Provision and run
cd D:\Projects\brane-mvp\paper\eval
uv venv --python 3.11
.\.venv\Scripts\Activate.ps1
uv pip install -r requirements.txt
```

**Option B — Python.org installer**
1. Install Python 3.11 from <https://www.python.org/downloads/> (tick "Add to PATH").
2. ```powershell
   cd D:\Projects\brane-mvp\paper\eval
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

## Run

**1. Smoke test (no deps required, ~1 second).** Verifies the BDP module's correctness properties: determinism, format preservation, vault roundtrip, asymmetric divergence, redaction.
```powershell
python smoke_test.py
```

**2. Generate the corpus** (no API key, ~1 second at bootstrap scale).
```powershell
python -m corpus
# -> data/patients.jsonl  (20 patients)
# -> data/notes.jsonl     (~200 notes)
# -> data/queries.jsonl   (100 queries, annotated with ground-truth note ids)
# -> data/roster.json     (identifier roster used by the lookup detector)
```

**3. Run the four-pipeline benchmark.** First run downloads the SBert model (~90 MB) and takes ~30 seconds; subsequent runs are <10 seconds.
```powershell
python -m run
# -> results/results.json  (machine-readable per-pipeline metrics)
# -> results/summary.md    (paste-into-paper-friendly tables)
```

## Switching to paper scale

Edit `config.py`:

```python
SCALE = PAPER_SCALE          # 1000 patients / ~10k notes / 5000 queries
EMBED_BACKEND = "openai"     # matches the manuscript's text-embedding-3-large
```

Set `OPENAI_API_KEY` in your environment (or a `.env` file consumed by your shell), then re-run `python -m corpus && python -m run`. Expect ~$20–40 in OpenAI spend per full pass and ~10–20 minutes wall time.

## What each pipeline does

| Pipeline | phi_w (write) | phi_r (read) | Identifier leak to embedder |
|---|---|---|---|
| `raw` | identity | identity | 100% (by construction) |
| `redact` | replace identifiers with `[NAME]`-style masks | same | 0% |
| `read_only` | **identity** | tokenize with BDP | **non-zero** (raw corpus leaks at index time) |
| `bdp` | tokenize with BDP | tokenize with BDP | 0% |

The `read_only` row is the silent-failure mode the paper formalizes. Watch its recall@5 vs `raw` (the asymmetry) and its leakage rate vs `bdp` (the false sense of privacy).

## Design notes

- **Detection is lookup-based, not Presidio.** The corpus generator emits a complete identifier roster, so detection in the eval is a deterministic string search. This deliberately isolates the BDP question from the orthogonal "how good is your NER?" question. Production deployments swap in Presidio + Indian-context recognizers; the BDP tokenizer itself is detector-agnostic.
- **No LLM calls during corpus generation.** Notes are templated, slot-filled from seeded RNG, fully reproducible from `SEED`. This is acknowledged in the manuscript's limitations (Section 8) as the trade-off for byte-reproducible eval.
- **Embedder defaults to SBert (MiniLM-L6-v2)** so the bootstrap runs on CPU with no API key. The asymmetry effect is observable across embedder choices; the *magnitude* of the gap may shift when you switch to `text-embedding-3-large`.
- **Single-chunk-per-note** for the bootstrap. Notes are short enough (~600 chars) that chunking adds complexity without insight at this scale. Add a chunker in `pipelines.py::Pipeline.index` for paper-scale runs over longer notes.

## When to scale up

The bootstrap exists to validate the harness, not to publish numbers. The manuscript's Table 1 and Figure 3 should be regenerated at `PAPER_SCALE` with `EMBED_BACKEND = "openai"`. The expected qualitative finding (read-only < redact < bdp ≈ raw on recall; 0% leak only for redact and bdp) should be visible even at bootstrap scale -- if it isn't, that's a harness bug, not a scientific finding.
