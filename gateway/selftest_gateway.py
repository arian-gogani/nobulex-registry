#!/usr/bin/env python3
"""Tests for the decision layer.

Every case here exists because the opposite behaviour is a way for this
gateway to report success without deciding anything. That is the defect the
rest of this repository is about, and a gateway is not exempt from it.

    python3 gateway/selftest_gateway.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "suite"))

from decide import (  # noqa: E402
    BLOCK, ESCALATE, EV_FAIL, EV_INDETERMINATE, EV_PASS, MODE_ENFORCE,
    MODE_OBSERVE, PERMIT, PolicyError, decide, ed25519_signer,
    evidence_status, receipt, sha256, validate_policy, verify_receipt,
)
from harness import (  # noqa: E402
    FAIL_SAFE, FAIL_UNSAFE, INDETERMINATE, OUT_OF_SCOPE, PASS,
)

FAILURES = []


def check(label, got, want):
    if got != want:
        FAILURES.append(f"{label}\n      got  {got!r}\n      want {want!r}")
        print(f"  FAIL  {label}")
    else:
        print(f"  ok    {label}")


def raises(label, fn, exc=PolicyError):
    try:
        fn()
    except exc:
        print(f"  ok    {label}")
        return
    except Exception as e:  # noqa: BLE001
        FAILURES.append(f"{label}: raised {type(e).__name__}, wanted {exc.__name__}")
        print(f"  FAIL  {label}")
        return
    FAILURES.append(f"{label}: returned instead of raising {exc.__name__}")
    print(f"  FAIL  {label}")


POLICY = {
    "id": "equity-order-v1",
    "version": 1,
    "on_evidence": {
        EV_PASS: PERMIT,
        EV_FAIL: BLOCK,
        EV_INDETERMINATE: ESCALATE,
    },
    "on_limit_violation": BLOCK,
    "limits": [
        {"field": "action.notional_usd", "op": "lte", "value": 50000,
         "code": "POLICY_NOTIONAL_WITHIN_LIMIT"},
        {"field": "evidence.quote.age_ms", "op": "lte", "value": 1000,
         "code": "QUOTE_FRESH"},
    ],
}

CTX_OK = {"action": {"notional_usd": 24130},
          "evidence": {"quote": {"age_ms": 84}}}


def main():
    print("Evidence status\n")
    # The all([]) case. A verdict aggregated over nothing is not a pass.
    check("no checks run is INDETERMINATE, never PASS",
          evidence_status([]), EV_INDETERMINATE)
    check("PASS alone is PASS", evidence_status([PASS]), EV_PASS)
    check("a quiet lie is FAIL", evidence_status([FAIL_UNSAFE]), EV_FAIL)
    check("one quiet lie dominates correct answers beside it",
          evidence_status([PASS, PASS, FAIL_UNSAFE, PASS]), EV_FAIL)
    # A refusal is not a false statement, so it is not FAIL. It is no evidence.
    check("an explicit refusal is INDETERMINATE, not FAIL",
          evidence_status([FAIL_SAFE]), EV_INDETERMINATE)
    check("unknown state is INDETERMINATE",
          evidence_status([INDETERMINATE]), EV_INDETERMINATE)
    check("out of scope is INDETERMINATE, never PASS",
          evidence_status([OUT_OF_SCOPE]), EV_INDETERMINATE)

    print("\nDecision\n")
    d = decide(POLICY, [PASS], CTX_OK)
    check("facts hold and limits satisfied permits", d["decision"], PERMIT)
    check("permitting does not claim a block", d["would_block"], False)

    d = decide(POLICY, [FAIL_UNSAFE], CTX_OK)
    check("false facts block", d["decision"], BLOCK)

    d = decide(POLICY, [FAIL_SAFE], CTX_OK)
    check("no evidence escalates rather than permitting",
          d["decision"], ESCALATE)

    d = decide(POLICY, [], CTX_OK)
    check("zero checks escalates rather than permitting",
          d["decision"], ESCALATE)
    check("zero checks is reported as zero checks", d["checks_run"], 0)

    over = {"action": {"notional_usd": 250000},
            "evidence": {"quote": {"age_ms": 84}}}
    d = decide(POLICY, [PASS], over)
    check("a violated limit blocks even with good facts",
          d["decision"], BLOCK)

    stale = {"action": {"notional_usd": 1000},
             "evidence": {"quote": {"age_ms": 862304}}}
    d = decide(POLICY, [PASS], stale)
    check("a stale quote blocks on the limit", d["decision"], BLOCK)

    print("\nA limit that cannot be evaluated is not satisfied\n")
    missing = {"action": {"notional_usd": 1000}, "evidence": {}}
    d = decide(POLICY, [PASS], missing)
    check("an absent field does not silently pass", d["decision"], BLOCK)
    check("and it is counted, not hidden", d["unevaluated_limits"], 1)

    wrong_type = {"action": {"notional_usd": "twenty thousand"},
                  "evidence": {"quote": {"age_ms": 84}}}
    d = decide(POLICY, [PASS], wrong_type)
    check("an incomparable value does not silently pass",
          d["decision"], BLOCK)

    print("\nPolicies this evaluator refuses to run\n")
    raises("a policy missing an evidence branch is rejected",
           lambda: validate_policy({"id": "x", "version": 1,
                                    "on_evidence": {EV_PASS: PERMIT}}))
    raises("an operator outside the bounded set is rejected",
           lambda: validate_policy({**POLICY, "limits": [
               {"field": "a", "op": "regex", "value": ".*", "code": "C"}]}))
    raises("a non-decision in on_evidence is rejected",
           lambda: validate_policy({**POLICY, "on_evidence": {
               EV_PASS: "allow", EV_FAIL: BLOCK,
               EV_INDETERMINATE: ESCALATE}}))

    print("\nObserve mode\n")
    d = decide(POLICY, [FAIL_UNSAFE], CTX_OK, mode=MODE_OBSERVE)
    check("observe still computes the decision", d["decision"], BLOCK)
    check("observe does not claim it enforced", d["enforced"], False)
    check("observe reports what it would have done",
          d["would_block"], True)
    d = decide(POLICY, [FAIL_UNSAFE], CTX_OK, mode=MODE_ENFORCE)
    check("enforce says so", d["enforced"], True)

    print("\nReceipts\n")
    action = {"type": "broker.order.create", "symbol": "AAPL",
              "quantity": 100, "notional_usd": 24130}
    d = decide(POLICY, [PASS], CTX_OK)
    refs = [{"type": "market.quote", "source_id": "primary",
             "observed_at": "2026-09-17T17:42:01Z",
             "content_hash": sha256({"p": 241.30})}]

    r = receipt(d, action, refs)
    check("an unsigned receipt says so rather than looking signed",
          r["signature"]["status"], "UNSIGNED")
    check("the receipt carries the decision", r["decision"], PERMIT)
    check("and the policy content hash",
          r["policy"]["content_hash"], sha256(POLICY))
    # The point is that the observed price itself never reaches the receipt,
    # only its hash. Asserting on the literal value rather than on a letter
    # that happens to appear in "primary", which is what this line used to do.
    check("and holds no raw payload, only hashes",
          "241.3" in str(r["evidence"]), False)

    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey)
        key = Ed25519PrivateKey.generate()
        priv = key.private_bytes_raw()
        pub = key.public_key().public_bytes_raw()

        signed = receipt(d, action, refs, signer=ed25519_signer(priv, "test-1"))
        check("a signed receipt says signed",
              signed["signature"]["status"], "SIGNED")
        ok, _ = verify_receipt(signed, pub)
        check("a signed receipt verifies", ok, True)

        tampered = dict(signed)
        tampered["decision"] = PERMIT if signed["decision"] != PERMIT else BLOCK
        ok, _ = verify_receipt(tampered, pub)
        check("a tampered decision fails verification", ok, False)

        other = Ed25519PrivateKey.generate().public_key().public_bytes_raw()
        ok, _ = verify_receipt(signed, other)
        check("a different key fails verification", ok, False)

        ok, why = verify_receipt(r, pub)
        check("an unsigned receipt does not verify", ok, False)
    except ImportError:
        print("  skip  signing tests, cryptography not installed")

    print("\nChaining\n")
    first = receipt(d, action, refs)
    second = receipt(d, action, refs, previous_hash=first["receipt_hash"])
    check("a receipt links to its predecessor",
          second["chain"]["previous_receipt_hash"], first["receipt_hash"])
    check("and a different body hashes differently",
          receipt(decide(POLICY, [FAIL_UNSAFE], CTX_OK), action,
                  refs)["receipt_hash"] != first["receipt_hash"], True)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} failed:\n")
        for f in FAILURES:
            print("  " + f)
        return 1
    print("all gateway checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
