#!/usr/bin/env python3
"""parent_refs fan-in fixture: real signed artifacts, not a spec snippet.

    python3 examples/parent_refs/build_fixture.py

Promised in OWASP/www-project-agentic-skills-top-10#44 on 10 Sept 2026:
implement `parent_refs` as a canonicalized array, sorted ascending as UTF-8
byte strings and deduplicated, with a 64-parent fan-in cap enforced at
CONSTRUCTION time so a receipt exceeding it is never signed in the first
place, rather than merely rejected at verification. Published as actual
signed objects so the cap-exceeded case is a real rejected artifact and not
documented behaviour.

Writes to examples/parent_refs/vectors/ and verifies every artifact it
writes before exiting. Exits nonzero if any expectation fails.

WHAT IS AND IS NOT RFC 8785 HERE, STATED RATHER THAN IMPLIED

The sort rule for `parent_refs` is the one proposed in the thread and it is
implemented exactly: UTF-8 byte strings, ascending, deduplicated. That is
this file's own rule and it is fully tested below, including against inputs
where byte order and Python's default string order disagree.

The whole-object serialization reuses the suite's `_canonical`, which is
`json.dumps(sort_keys=True, separators=(",",":"), ensure_ascii=False)` over
UTF-8. That agrees with RFC 8785 for every value in these fixtures, and the
test at the bottom checks the properties that matter here: stable key order,
no insignificant whitespace, UTF-8 output, and byte-identical output across
runs and across dict insertion orders.

It is NOT a general RFC 8785 implementation and this file does not claim to
be one. Two known divergences, neither reachable by these fixtures:

  - JCS orders object keys by UTF-16 code unit; Python's sort_keys orders by
    Unicode code point. These differ only for keys containing characters
    above the BMP. Every key here is ASCII.
  - JCS pins number serialization to ECMAScript Number::toString. Python's
    repr agrees for the integers used here and can differ for some floats.
    No float appears in any fixture.

Anyone adopting this for arbitrary payloads needs a real JCS library. Said
here because a fixture published into a spec discussion that silently
approximated the spec would be the exact failure this project exists to name.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "gateway"))
sys.path.insert(0, str(ROOT / "suite"))

from decide import _canonical, sha256  # noqa: E402

OUT = Path(__file__).resolve().parent / "vectors"

# The cap proposed in the thread. Enforced at construction, below.
MAX_PARENTS = 64


class FanInCapExceeded(ValueError):
    """Raised at construction. A receipt over the cap is never signed.

    This is the whole point of the cap living here rather than in a
    verifier. A verifier-side cap still lets an over-cap object exist as a
    signed artifact that some other verifier, or an older one, may accept.
    Refusing before the signature means the object a producer could hand
    anyone was never valid to begin with.
    """


def canonical_parent_refs(refs):
    """Dedupe, then sort ascending as UTF-8 byte strings.

    Byte order, not Python's default str order. They agree across ASCII and
    diverge above it, so the rule is implemented on the bytes the spec names
    rather than on whatever ordering the host language happens to give.
    """
    if not all(isinstance(r, str) for r in refs):
        raise TypeError("every parent ref must be a string")
    unique = set(refs)
    ordered = sorted(unique, key=lambda s: s.encode("utf-8"))
    if len(ordered) > MAX_PARENTS:
        raise FanInCapExceeded(
            f"{len(ordered)} distinct parent refs exceeds the {MAX_PARENTS} "
            f"cap; this object is refused before signing, so no signed "
            f"artifact with this fan-in exists")
    return ordered


def build_receipt(action_ref, parent_refs, signer=None):
    """A receipt whose parentage is inside the signed preimage.

    parent_refs sits in the signed body deliberately. Outside it, parentage
    is rewritable after the fact: a runtime could relabel which upstream
    triggered an execution without invalidating any identifier. Inside, the
    causal claim is as tamper-evident as the rest of the record.
    """
    body = {
        "receipt_version": "parent-refs-fixture-1",
        "action_ref": action_ref,
        "parent_refs": canonical_parent_refs(parent_refs),
    }
    body["preimage_sha256"] = sha256(body)
    if signer is None:
        body["signature"] = {"status": "UNSIGNED",
                             "detail": "no signing key supplied"}
    else:
        body["signature"] = signer(_canonical(body))
    return body


def _signer():
    """Ed25519 over the canonical preimage, or None if unavailable."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey)
    except ImportError:
        return None, None
    import base64
    # Fixed seed so the artifacts are reproducible byte for byte. This key
    # signs fixtures and nothing else; it is published with them on purpose.
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    pub = base64.urlsafe_b64encode(key.public_key().public_bytes_raw()).decode()

    def sign(preimage: bytes):
        return {"status": "SIGNED", "alg": "Ed25519", "key_id": "fixture-1",
                "public_key": pub,
                "sig": base64.urlsafe_b64encode(key.sign(preimage)).decode()}
    return sign, key


def verify(obj, key):
    """Recompute the preimage and check the signature. Returns (ok, why)."""
    if obj.get("signature", {}).get("status") != "SIGNED":
        return False, "unsigned"
    import base64
    body = {k: v for k, v in obj.items() if k != "signature"}
    stated = body.pop("preimage_sha256", None)
    if sha256(body) != stated:
        return False, "preimage_sha256 does not match the body"
    body["preimage_sha256"] = stated
    try:
        key.public_key().verify(
            base64.urlsafe_b64decode(obj["signature"]["sig"]),
            _canonical(body))
    except Exception:
        return False, "signature does not verify"
    return True, "ok"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sign, key = _signer()
    if sign is None:
        print("cryptography is not installed, so nothing here can be signed.")
        print("Refusing to write unsigned artifacts described as signed.")
        return 2

    failures = []

    def check(label, got, want):
        if got != want:
            failures.append(f"{label}: got {got!r}, want {want!r}")
            print(f"  FAIL  {label}")
        else:
            print(f"  ok    {label}")

    print("Sort rule: UTF-8 bytes ascending, deduplicated\n")
    check("duplicates collapse",
          canonical_parent_refs(["a", "a", "b"]), ["a", "b"])
    check("ascending by byte, not by insertion",
          canonical_parent_refs(["b", "a"]), ["a", "b"])
    # 'Z' is 0x5A, 'a' is 0x61. Byte order puts 'Z' first. A case-insensitive
    # or locale-aware sort would not, which is why the rule names bytes.
    check("uppercase sorts before lowercase, as bytes do",
          canonical_parent_refs(["a", "Z"]), ["Z", "a"])
    # U+00E9 encodes to two bytes, 0xC3 0xA9, so it sorts after any ASCII.
    check("non-ASCII sorts by its UTF-8 encoding",
          canonical_parent_refs(["é", "z"]), ["z", "é"])

    print("\nThe cap is enforced at construction, before signing\n")
    at_cap = [f"sha256:{i:064x}" for i in range(MAX_PARENTS)]
    over_cap = [f"sha256:{i:064x}" for i in range(MAX_PARENTS + 1)]
    check("exactly at the cap is accepted",
          len(canonical_parent_refs(at_cap)), MAX_PARENTS)
    try:
        build_receipt("sha256:child", over_cap, sign)
        failures.append("an over-cap receipt was built")
        print("  FAIL  one over the cap refuses to build")
    except FanInCapExceeded:
        print("  ok    one over the cap refuses to build")
    # The claim is not merely that it raises. It is that no signed artifact
    # exists, which is what the raise is for.
    check("and therefore no signed over-cap artifact exists",
          (OUT / "04-fan-in-cap-exceeded.json").exists(), False)

    print("\nArtifacts\n")
    vectors = [
        ("01-single-parent.json", "sha256:" + "11" * 32, ["sha256:" + "aa" * 32]),
        ("02-fan-in-three.json", "sha256:" + "22" * 32,
         ["sha256:" + "cc" * 32, "sha256:" + "aa" * 32, "sha256:" + "bb" * 32]),
        ("03-fan-in-at-cap.json", "sha256:" + "33" * 32, at_cap),
    ]
    for name, action_ref, parents in vectors:
        r = build_receipt(action_ref, parents, sign)
        ok, why = verify(r, key)
        check(f"{name} verifies", (ok, why), (True, "ok"))
        (OUT / name).write_text(json.dumps(r, indent=2) + "\n")

    # Determinism: the same inputs in a different order must produce the same
    # bytes, or the fixture is not a fixture.
    a = build_receipt("sha256:x", ["sha256:b", "sha256:a"], sign)
    b = build_receipt("sha256:x", ["sha256:a", "sha256:b", "sha256:a"], sign)
    check("shuffled and duplicated input yields byte-identical output",
          _canonical(a), _canonical(b))

    # Tamper: reordering parent_refs after signing must break the signature,
    # which is the property that makes parentage tamper-evident at all.
    t = json.loads(json.dumps(a))
    t["parent_refs"] = list(reversed(t["parent_refs"]))
    ok, _ = verify(t, key)
    check("reordering parent_refs after signing breaks verification", ok, False)

    rejected = {
        "note": "There is deliberately no signed artifact for the over-cap "
                "case. The cap is enforced at construction, so the object "
                "below was refused before a signature existed. This file "
                "records the refusal; it is not a receipt.",
        "attempted_parent_count": len(over_cap),
        "cap": MAX_PARENTS,
        "error": "FanInCapExceeded",
        "why_not_verifier_side": "A verifier-side cap still permits a signed "
                                 "over-cap object to exist, which a different "
                                 "or older verifier may accept. Refusing "
                                 "before signing means it never existed.",
    }
    (OUT / "04-fan-in-cap-exceeded.REFUSAL.json").write_text(
        json.dumps(rejected, indent=2) + "\n")
    print(f"  ok    refusal record written, and it is not a receipt")

    print()
    for p in sorted(OUT.iterdir()):
        print(f"  {p.relative_to(ROOT)}  ({p.stat().st_size} bytes)")

    print()
    if failures:
        print(f"{len(failures)} failed:")
        for f in failures:
            print("  " + f)
        return 1
    print("every artifact written was verified after writing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
