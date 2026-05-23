"""
The four pipelines compared in the paper.

Each pipeline implements:
    index(notes)             ingest the corpus into a vector store
    query(text) -> ids       retrieve top-k note ids for a query
    outbound_payloads        list of every string that left the trust boundary
                             (i.e. was sent to the embedding API). Used by the
                             leakage metric.

Pipelines share the same Store + Embedder; the only thing that varies is the
text-normalization function applied at write time (phi_w) and at read time
(phi_r). The whole point of the paper is to characterize what happens when
phi_w != phi_r.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Sequence

from config import TOP_K
from bdp import (
    LookupDetector, Vault,
    tokenize_text, redact_text,
)
from embed import Store, get_embedder


@dataclass
class IndexedNote:
    note_id: str
    text: str


class Pipeline:
    name: str = "base"

    def __init__(self, detector: LookupDetector):
        self.detector = detector
        self.store = Store(get_embedder())
        self.outbound_payloads: list[str] = []

    # ---- phi_w / phi_r: override in subclasses ------------------------------
    def phi_w(self, text: str) -> str:
        return text

    def phi_r(self, text: str) -> str:
        return text

    # ---- main API -----------------------------------------------------------
    def index(self, notes: Sequence[IndexedNote]) -> None:
        transformed = [self.phi_w(n.text) for n in notes]
        self.outbound_payloads.extend(transformed)   # what the embedder sees
        self.store.index([n.note_id for n in notes], transformed)

    def query(self, text: str, k: int = max(TOP_K)) -> list[str]:
        q = self.phi_r(text)
        self.outbound_payloads.append(q)
        return self.store.query(q, k=k)


# ---------------------------------------------------------------------------
# The four pipelines
# ---------------------------------------------------------------------------

class RawPipeline(Pipeline):
    """Upper bound on retrieval. Not a permissible deployment -- leaks 100%."""
    name = "raw"


class RedactPipeline(Pipeline):
    """Symmetric one-way redaction with fixed mask tokens. phi_w == phi_r."""
    name = "redact"

    def phi_w(self, text: str) -> str:
        return redact_text(text, self.detector)

    def phi_r(self, text: str) -> str:
        return redact_text(text, self.detector)


class ReadOnlyPipeline(Pipeline):
    """
    The widespread footgun. Indexed corpus is unmodified; only the query is
    tokenized. phi_w = identity, phi_r = BDP tokenization.

    Two failure modes are visible in this design:
      1. Retrieval asymmetry -- query embedding shifts away from the matching
         document embedding because identifiers are replaced on only one side.
      2. Ingestion-time leakage -- the full raw corpus is sent to the embedder
         at index time, which is exactly what the privacy posture was supposed
         to prevent.
    """
    name = "read_only"

    def __init__(self, detector: LookupDetector):
        super().__init__(detector)
        self.vault = Vault()

    def phi_w(self, text: str) -> str:
        return text  # raw -- this is the bug

    def phi_r(self, text: str) -> str:
        return tokenize_text(text, self.detector, vault=self.vault)


class BDPPipeline(Pipeline):
    """
    Bidirectional Deterministic Pseudonymization. phi_w == phi_r == phi_BDP.
    Vault is populated at ingest time and reused for symmetric query-side
    tokenization, giving us byte-identical tokens on both sides.
    """
    name = "bdp"

    def __init__(self, detector: LookupDetector):
        super().__init__(detector)
        self.vault = Vault()

    def phi_w(self, text: str) -> str:
        return tokenize_text(text, self.detector, vault=self.vault)

    def phi_r(self, text: str) -> str:
        # Vault already populated; this call only adds tokens for identifiers
        # that appear in the query but not in any indexed document (rare).
        return tokenize_text(text, self.detector, vault=self.vault)


PIPELINE_REGISTRY = {
    "raw":       RawPipeline,
    "redact":    RedactPipeline,
    "read_only": ReadOnlyPipeline,
    "bdp":       BDPPipeline,
}
