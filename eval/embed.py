"""
Embedding + retrieval. Two backends:

  - "sbert"  : sentence-transformers/all-MiniLM-L6-v2 (local, CPU, free, default)
  - "openai" : text-embedding-3-large (matches the paper; requires OPENAI_API_KEY)

Retrieval is a simple in-memory cosine top-k. This is sufficient at bootstrap
scale; for the full paper run swap in pgvector or Chroma -- the Pipeline ABC
doesn't care.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Sequence

import numpy as np

from config import EMBED_BACKEND, OPENAI_EMBED_MODEL, SBERT_MODEL


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

class Embedder:
    def encode(self, texts: Sequence[str]) -> np.ndarray:
        raise NotImplementedError


class SBertEmbedder(Embedder):
    def __init__(self, model_name: str = SBERT_MODEL):
        from sentence_transformers import SentenceTransformer  # heavy import, lazy
        self.model = SentenceTransformer(model_name)

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        return np.asarray(self.model.encode(list(texts), normalize_embeddings=True))


class OpenAIEmbedder(Embedder):
    def __init__(self, model_name: str = OPENAI_EMBED_MODEL):
        from openai import OpenAI
        self.client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        self.model_name = model_name

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        # Batch in chunks of 256 to stay under per-request limits.
        out: list[np.ndarray] = []
        batch = 256
        for i in range(0, len(texts), batch):
            resp = self.client.embeddings.create(
                model=self.model_name,
                input=list(texts[i:i + batch]),
            )
            out.extend(np.asarray(d.embedding) for d in resp.data)
        m = np.vstack(out)
        # Normalize for cosine = dot
        norms = np.linalg.norm(m, axis=1, keepdims=True)
        return m / np.clip(norms, 1e-12, None)


@lru_cache(maxsize=1)
def get_embedder() -> Embedder:
    if EMBED_BACKEND == "sbert":
        return SBertEmbedder()
    if EMBED_BACKEND == "openai":
        return OpenAIEmbedder()
    raise ValueError(f"unknown EMBED_BACKEND: {EMBED_BACKEND}")


# ---------------------------------------------------------------------------
# In-memory vector store
# ---------------------------------------------------------------------------

class Store:
    """Cosine top-k retrieval over a fixed corpus. Embeddings are L2-normalized."""

    def __init__(self, embedder: Embedder):
        self.embedder = embedder
        self.ids: list[str] = []
        self.matrix: np.ndarray | None = None

    def index(self, ids: Sequence[str], texts: Sequence[str]) -> None:
        assert len(ids) == len(texts)
        self.ids = list(ids)
        self.matrix = self.embedder.encode(texts)

    def query(self, text: str, k: int = 10) -> list[str]:
        assert self.matrix is not None, "index() before query()"
        qv = self.embedder.encode([text])[0]
        sims = self.matrix @ qv
        top = np.argsort(-sims)[:k]
        return [self.ids[i] for i in top]
