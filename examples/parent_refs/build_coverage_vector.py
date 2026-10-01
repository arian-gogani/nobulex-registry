#!/usr/bin/env python3
"""Write a signed join whose two parents must both be visited.

The fixture distinguishes a complete reconstruction from a verifier that
supports only one parent. It cannot prove that unrecorded real-world actions
do not exist; completeness is relative to the supplied signed graph.
"""

import json
from pathlib import Path

from build_fixture import _signer, build_receipt
from causal_coverage import reconstruct


OUT = Path(__file__).resolve().parent / "vectors" / "06-fan-in-coverage.json"
LEFT = "sha256:" + "a1" * 32
RIGHT = "sha256:" + "b2" * 32
JOIN = "sha256:" + "c3" * 32


def make_vector():
    signer, key = _signer()
    if signer is None:
        raise RuntimeError("cryptography is required; no signed vector written")
    records = {
        LEFT: build_receipt(LEFT, [], signer),
        RIGHT: build_receipt(RIGHT, [], signer),
        JOIN: build_receipt(JOIN, [RIGHT, LEFT], signer),
    }
    complete = reconstruct(records, JOIN, key)
    limited = reconstruct(records, JOIN, key, fan_in_supported=False)
    if (complete.get("status") != "COMPLETE" or
            complete.get("roots") != [LEFT, RIGHT] or
            complete.get("visited") != 3 or
            limited.get("status") != "INCOMPLETE" or
            limited.get("reason") != "fan_in_unsupported"):
        raise AssertionError("coverage expectations do not hold; refusing fixture")
    return {
        "fixture_version": "parent-refs-coverage-1",
        "head_ref": JOIN,
        "records": records,
        "expected": {
            "fan_in_verifier": complete,
            "single_parent_only_verifier": limited,
        },
        "claim_limit": "Complete means every parent named by the supplied signed "
                       "records reached a root. It does not prove that no "
                       "other real-world action occurred.",
    }


def main():
    vector = make_vector()
    OUT.write_text(json.dumps(vector, indent=2) + "\n")
    # Re-read the published bytes and verify their verdicts, not just the
    # in-memory objects from which they were built.
    loaded = json.loads(OUT.read_text())
    _, key = _signer()
    for label, supported in (("fan_in_verifier", True),
                             ("single_parent_only_verifier", False)):
        got = reconstruct(loaded["records"], loaded["head_ref"], key,
                          fan_in_supported=supported)
        if got != loaded["expected"][label]:
            raise AssertionError(f"published {label} verdict changed")
        print(f"{label}: {got['status']} ({got['reason']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
