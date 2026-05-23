"""
Central config for the BDP eval harness.

Bootstrap scale by default (20 patients / ~200 notes / 100 queries) so the full
benchmark runs end-to-end in a few minutes on CPU with no API key. To reproduce
the paper's headline numbers, switch to PAPER_SCALE and provide OPENAI_API_KEY.
"""
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
RESULTS_DIR = ROOT / "results"

# Deterministic seed for corpus generation, token derivation, embedding shuffles.
SEED = 42

# Tenant key for HMAC tokenization. In production this is a per-tenant secret
# stored in the controller's KMS. For the synthetic eval it is a fixed string
# so that runs are byte-reproducible.
TENANT_KEY = b"brane-eval-tenant-key-do-not-use-in-production"

# Corpus scale.
BOOTSTRAP_SCALE = dict(
    n_patients=20,
    notes_per_patient=(8, 12),    # uniform int range, inclusive
    n_queries=100,
    query_split=dict(lookup=0.34, longitudinal=0.33, reasoning=0.33),
)

PAPER_SCALE = dict(
    n_patients=1000,
    notes_per_patient=(8, 12),
    n_queries=5000,
    query_split=dict(lookup=0.34, longitudinal=0.33, reasoning=0.33),
)

SCALE = BOOTSTRAP_SCALE   # flip to PAPER_SCALE for the full paper run

# Embedding backend.
#   "sbert"  -> sentence-transformers/all-MiniLM-L6-v2 (default, local, free)
#   "openai" -> text-embedding-3-large (matches paper; requires OPENAI_API_KEY)
EMBED_BACKEND = "sbert"
SBERT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
OPENAI_EMBED_MODEL = "text-embedding-3-large"

# Retrieval.
TOP_K = (1, 5, 10)
CHUNK_SIZE_CHARS = 800   # notes are short; one chunk per note for the bootstrap

# Pipelines to evaluate. Order matters only for display.
PIPELINES = ["raw", "redact", "read_only", "bdp"]
