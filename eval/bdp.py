"""
Bidirectional Deterministic Pseudonymization (BDP) -- reference implementation.

This module is the Python counterpart to the TypeScript SDK shipped in the Brane
repo. It is intentionally small and dependency-free so the eval harness can be
audited end-to-end.

Construction (see paper Section 5.2):
    tau(s, c) = F_c( HMAC-SHA256(K, c || s) )

where:
    - s is the raw identifier string
    - c is the identifier category (NAME, DATE, PHONE, MRN, ABHA, PINCODE, ADDR)
    - K is the tenant-scoped key
    - F_c is a category-specific format-preserving decoder (a name -> a name,
      a date -> a date, a phone -> a phone). Surrogate vocabularies are fixed
      per category and indexed by the HMAC output.

The mapping (s, tau(s,c)) is also written to the Vault so authorized
downstream consumers can invert the tokenization at the controller boundary.

Identifier detection for the synthetic corpus is lookup-based: the corpus
generator emits a per-patient identifier roster, and the detector simply
finds occurrences. A production deployment swaps this for Microsoft Presidio
extended with Indian-context recognizers; the BDP tokenizer itself is
detector-agnostic.
"""
from __future__ import annotations

import hmac
import hashlib
import json
import re
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

from config import TENANT_KEY


# ---------------------------------------------------------------------------
# Surrogate vocabularies for format-preserving decoders.
# Pulled from a separate, disjoint name pool so surrogate tokens cannot collide
# with raw corpus names. (Vocabulary lists deliberately small for the bootstrap.)
# ---------------------------------------------------------------------------

SURROGATE_FIRST_NAMES = [
    "Aarav", "Vivaan", "Aditya", "Vihaan", "Arjun", "Sai", "Reyansh", "Ayaan",
    "Krishna", "Ishaan", "Ananya", "Diya", "Saanvi", "Aadhya", "Myra",
    "Anika", "Navya", "Kiara", "Riya", "Pari", "Ira", "Mira", "Tara",
    "Kabir", "Aryan", "Rohan", "Kunal", "Veer", "Yash", "Dev",
]
SURROGATE_LAST_NAMES = [
    "Sharma", "Verma", "Iyer", "Nair", "Menon", "Reddy", "Rao", "Patel",
    "Shah", "Mehta", "Gupta", "Banerjee", "Bose", "Chatterjee", "Das",
    "Pillai", "Krishnan", "Subramanian", "Kulkarni", "Joshi",
]


# ---------------------------------------------------------------------------
# Token derivation
# ---------------------------------------------------------------------------

def _hmac_bytes(category: str, value: str, key: bytes = TENANT_KEY) -> bytes:
    msg = f"{category}||{value}".encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).digest()


def _hmac_int(category: str, value: str, key: bytes = TENANT_KEY) -> int:
    return int.from_bytes(_hmac_bytes(category, value, key), "big")


# ---------------------------------------------------------------------------
# Format-preserving decoders F_c
# ---------------------------------------------------------------------------

def decode_name(value: str) -> str:
    """Name -> name. Preserves first+last structure if present."""
    h = _hmac_int("NAME", value)
    parts = value.strip().split()
    if len(parts) >= 2:
        first = SURROGATE_FIRST_NAMES[h % len(SURROGATE_FIRST_NAMES)]
        last = SURROGATE_LAST_NAMES[(h >> 16) % len(SURROGATE_LAST_NAMES)]
        return f"{first} {last}"
    return SURROGATE_FIRST_NAMES[h % len(SURROGATE_FIRST_NAMES)]


def decode_date(value: str, max_shift_days: int = 30) -> str:
    """
    Date -> date. Deterministic offset within +/- max_shift_days, day-of-week
    preserved (offset is always a multiple of 7).
    Accepts ISO YYYY-MM-DD; emits the same format.
    """
    h = _hmac_int("DATE", value)
    weeks = (h % (2 * max_shift_days // 7 + 1)) - (max_shift_days // 7)
    try:
        d = date.fromisoformat(value)
    except ValueError:
        return value
    shifted = d + timedelta(weeks=weeks)
    return shifted.isoformat()


def decode_phone(value: str) -> str:
    """Phone -> syntactically valid but unallocated Indian mobile range."""
    h = _hmac_int("PHONE", value)
    suffix = f"{h % 1_000_000:06d}"
    return f"+91-7000-{suffix}"


def decode_mrn(value: str) -> str:
    h = _hmac_int("MRN", value)
    return f"MRN-{h % 10_000_000:07d}"


def decode_abha(value: str) -> str:
    """ABHA ID -> 14-digit deterministic surrogate, Luhn-style group-of-4 format."""
    h = _hmac_int("ABHA", value)
    s = f"{h % 10**14:014d}"
    return f"{s[0:2]}-{s[2:6]}-{s[6:10]}-{s[10:14]}"


def decode_pincode(value: str) -> str:
    """Indian pincode (6 digits). Preserve first two (state/region) for utility."""
    h = _hmac_int("PINCODE", value)
    if len(value) == 6 and value.isdigit():
        return value[:2] + f"{h % 10000:04d}"
    return f"{h % 1_000_000:06d}"


def decode_address(value: str) -> str:
    h = _hmac_int("ADDR", value)
    streets = ["MG Road", "Brigade Road", "Anna Salai", "Park Street",
               "Linking Road", "Lajpat Nagar", "Indiranagar 100ft Road"]
    return f"{(h % 999) + 1} {streets[h % len(streets)]}"


DECODERS = {
    "NAME":    decode_name,
    "DATE":    decode_date,
    "PHONE":   decode_phone,
    "MRN":     decode_mrn,
    "ABHA":    decode_abha,
    "PINCODE": decode_pincode,
    "ADDR":    decode_address,
}


# ---------------------------------------------------------------------------
# Vault
# ---------------------------------------------------------------------------

@dataclass
class Vault:
    """
    Bidirectional map: (category, raw) <-> token.
    In production this is a controller-side service backed by an encrypted
    store; here it's an in-memory dict serializable to JSON for audit.
    """
    forward: dict = field(default_factory=dict)   # f"{cat}::{raw}" -> token
    reverse: dict = field(default_factory=dict)   # token -> raw

    def put(self, category: str, raw: str, token: str) -> None:
        self.forward[f"{category}::{raw}"] = token
        self.reverse[token] = raw

    def get_token(self, category: str, raw: str) -> str | None:
        return self.forward.get(f"{category}::{raw}")

    def get_raw(self, token: str) -> str | None:
        return self.reverse.get(token)

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls, path: Path) -> "Vault":
        return cls(**json.loads(path.read_text()))


# ---------------------------------------------------------------------------
# Identifier detection (lookup-based for the synthetic eval)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Span:
    start: int
    end: int
    category: str
    value: str

    def __lt__(self, other: "Span") -> bool:
        return (self.start, -self.end) < (other.start, -other.end)


class LookupDetector:
    """
    Finds occurrences of a known identifier roster in text.

    The synthetic-corpus generator emits the full roster of identifiers it
    used, so detection in the eval is a deterministic string search rather
    than NER. This isolates the BDP question from the orthogonal question
    of NER quality (which is itself a paper-worthy subject -- see Section 8,
    'NER quality bound').
    """
    def __init__(self, roster: list[tuple[str, str]]):
        # roster: list of (category, value) pairs across the entire corpus
        # Longest-match-first so "Rahul Sharma" beats "Rahul".
        self.roster = sorted(set(roster), key=lambda r: -len(r[1]))

    def detect(self, text: str) -> list[Span]:
        spans: list[Span] = []
        taken = [False] * len(text)
        for category, value in self.roster:
            if not value:
                continue
            for m in re.finditer(re.escape(value), text):
                s, e = m.span()
                if not any(taken[s:e]):
                    spans.append(Span(s, e, category, value))
                    for i in range(s, e):
                        taken[i] = True
        spans.sort()
        return spans


# ---------------------------------------------------------------------------
# Tokenization API
# ---------------------------------------------------------------------------

def tokenize_value(category: str, value: str, vault: Vault | None = None) -> str:
    """Compute tau(value, category) and (optionally) record it in the vault."""
    decoder = DECODERS.get(category)
    if decoder is None:
        raise ValueError(f"unknown category: {category}")
    token = decoder(value)
    if vault is not None:
        vault.put(category, value, token)
    return token


def tokenize_text(
    text: str,
    detector: LookupDetector,
    vault: Vault | None = None,
) -> str:
    """Apply phi_BDP to text. The same function is used at write- and read-time."""
    spans = detector.detect(text)
    out: list[str] = []
    cursor = 0
    for span in spans:
        out.append(text[cursor:span.start])
        out.append(tokenize_value(span.category, span.value, vault))
        cursor = span.end
    out.append(text[cursor:])
    return "".join(out)


def detokenize_text(text: str, vault: Vault) -> str:
    """Inverse of tokenize_text. Used at the controller boundary on rendered output."""
    # Replace longest tokens first to avoid prefix collisions.
    for token in sorted(vault.reverse.keys(), key=lambda t: -len(t)):
        text = text.replace(token, vault.reverse[token])
    return text


# ---------------------------------------------------------------------------
# Redaction baseline (for the Redact pipeline, not BDP)
# ---------------------------------------------------------------------------

CATEGORY_MASK = {
    "NAME":    "[NAME]",
    "DATE":    "[DATE]",
    "PHONE":   "[PHONE]",
    "MRN":     "[MRN]",
    "ABHA":    "[ABHA]",
    "PINCODE": "[PINCODE]",
    "ADDR":    "[ADDRESS]",
}


def redact_text(text: str, detector: LookupDetector) -> str:
    spans = detector.detect(text)
    out: list[str] = []
    cursor = 0
    for span in spans:
        out.append(text[cursor:span.start])
        out.append(CATEGORY_MASK[span.category])
        cursor = span.end
    out.append(text[cursor:])
    return "".join(out)
