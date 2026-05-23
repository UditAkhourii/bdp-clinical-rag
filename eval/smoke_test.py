"""
Dependency-free smoke test for the BDP module.

Runs without numpy, torch, sentence-transformers -- only stdlib. Verifies:
  - Tokenization is deterministic (same input -> same token, two ways)
  - Format is preserved (a name comes back as a name-shaped string)
  - Detokenize is the inverse of tokenize on the same vault
  - Read-only asymmetry actually produces different strings on each side
  - Redaction collapses identifiers to the fixed mask

  python -m smoke_test
"""
from __future__ import annotations

import sys

from bdp import (
    LookupDetector, Vault,
    tokenize_value, tokenize_text, detokenize_text, redact_text,
    DECODERS,
)


ROSTER = [
    ("NAME",    "Rahul Kumar"),
    ("NAME",    "Priya Singh"),
    ("MRN",     "MRN-1234567"),
    ("PHONE",   "+91-9876543210"),
    ("ABHA",    "12-3456-7890-1234"),
    ("PINCODE", "560001"),
]


def test_determinism() -> None:
    t1 = tokenize_value("NAME", "Rahul Kumar")
    t2 = tokenize_value("NAME", "Rahul Kumar")
    assert t1 == t2, f"non-deterministic: {t1} vs {t2}"
    assert t1 != "Rahul Kumar", "tokenization returned the input"
    print(f"  determinism OK   Rahul Kumar -> {t1}")


def test_format_preservation() -> None:
    name_tok = tokenize_value("NAME", "Rahul Kumar")
    assert len(name_tok.split()) == 2, f"name lost its bipartite structure: {name_tok}"
    phone_tok = tokenize_value("PHONE", "+91-9876543210")
    assert phone_tok.startswith("+91-"), f"phone lost its prefix: {phone_tok}"
    pin_tok = tokenize_value("PINCODE", "560001")
    assert pin_tok.startswith("56") and len(pin_tok) == 6, \
        f"pincode lost region prefix or length: {pin_tok}"
    print(f"  format preserved OK   phone -> {phone_tok}   pin -> {pin_tok}")


def test_roundtrip() -> None:
    text = (
        "Patient: Rahul Kumar, MRN MRN-1234567, ABHA 12-3456-7890-1234, "
        "phone +91-9876543210, pincode 560001. BP 140/90."
    )
    detector = LookupDetector(ROSTER)
    vault = Vault()
    tok = tokenize_text(text, detector, vault=vault)
    assert "Rahul Kumar" not in tok, "raw name leaked through tokenize_text"
    assert "MRN-1234567" not in tok, "raw MRN leaked"
    assert "140/90" in tok, "clinical value was incorrectly tokenized"
    back = detokenize_text(tok, vault)
    assert back == text, f"roundtrip mismatch:\n  in : {text}\n  out: {back}"
    print(f"  roundtrip OK   {len(vault.forward)} identifiers vaulted")


def test_asymmetry_produces_divergence() -> None:
    """The whole reason the paper exists: phi_w != phi_r -> different strings."""
    text = "Patient Rahul Kumar with MRN MRN-1234567 has HbA1c 8.2%."
    query = "What is Rahul Kumar's latest HbA1c?"
    detector = LookupDetector(ROSTER)
    vault = Vault()

    # Read-only: phi_w identity, phi_r BDP
    write_side = text                                       # phi_w(text)
    read_side  = tokenize_text(query, detector, vault=vault)  # phi_r(query)
    assert "Rahul Kumar" in write_side
    assert "Rahul Kumar" not in read_side
    # The very point: the token in read_side does not appear in write_side.
    for tok in vault.reverse:
        if tok in read_side:
            assert tok not in write_side, "asymmetry should produce a token mismatch"
    print(f"  asymmetry demonstrated   read-side carries {sorted(vault.reverse)[:1]}")


def test_redaction_collapses() -> None:
    text = "Patient Rahul Kumar with MRN MRN-1234567 phone +91-9876543210."
    detector = LookupDetector(ROSTER)
    redacted = redact_text(text, detector)
    assert "[NAME]" in redacted and "[MRN]" in redacted and "[PHONE]" in redacted
    assert "Rahul" not in redacted
    print(f"  redaction OK   -> {redacted}")


def main() -> int:
    tests = [
        test_determinism,
        test_format_preservation,
        test_roundtrip,
        test_asymmetry_produces_divergence,
        test_redaction_collapses,
    ]
    for t in tests:
        print(f"[smoke] {t.__name__}")
        t()
    print(f"\n[smoke] OK -- all {len(tests)} tests passed.  Decoders covered: {sorted(DECODERS)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
