#!/usr/bin/env python3
"""Tests for the wrapper. The two properties that matter:

observe mode cannot change the wrapped call's behaviour, no matter what,
and in enforce mode the gateway's own failure is the caller's stated
choice, never a silent approval.

    python3 gateway/selftest_observe.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "suite"))

from decide import BLOCK, ESCALATE, EV_FAIL, EV_INDETERMINATE, EV_PASS, PERMIT  # noqa: E402
from observe import ENFORCE, OBSERVE, Blocked, guard  # noqa: E402

FAILURES = []


def check(label, got, want):
    if got != want:
        FAILURES.append(f"{label}: got {got!r}, want {want!r}")
        print(f"  FAIL  {label}")
    else:
        print(f"  ok    {label}")


POLICY = {
    "id": "wrap-test", "version": 1,
    "on_evidence": {EV_PASS: PERMIT, EV_FAIL: BLOCK,
                    EV_INDETERMINATE: ESCALATE},
    "on_limit_violation": BLOCK,
    "limits": [],
}


def fetch_good():
    """Stands in for the call being mirrored."""
    return {"bars": 5}


class Boom(Exception):
    pass


def fetch_raises():
    raise Boom("upstream fell over")


def main():
    log = []

    def on_decision(d, r):
        log.append((d, r))

    print("Observe mode cannot change the call\n")

    g = guard(fetch_good, checks=lambda res, ctx: ["PASS"], policy=POLICY,
              on_decision=on_decision)
    check("result passes through unchanged", g(), {"bars": 5})
    check("a decision was emitted", len(log), 1)
    check("and it permitted", log[-1][0]["decision"], PERMIT)
    check("and carried a receipt", log[-1][1]["receipt_hash"][:7], "sha256:")

    g = guard(fetch_good, checks=lambda res, ctx: ["FAIL_UNSAFE"],
              policy=POLICY, on_decision=on_decision)
    check("a blocked verdict still returns the result in observe",
          g(), {"bars": 5})
    check("but records it would have blocked", log[-1][0]["would_block"], True)

    g = guard(fetch_good, checks=lambda res, ctx: 1 / 0, policy=POLICY,
              on_decision=on_decision)
    check("the checks raising still returns the result in observe",
          g(), {"bars": 5})
    check("and the error decision is an escalate, not a permit",
          log[-1][0]["decision"], ESCALATE)
    check("with GATEWAY_ERROR named",
          log[-1][0]["reasons"][0]["code"], "GATEWAY_ERROR")

    def broken_consumer(d, r):
        raise RuntimeError("the log pipeline is down")
    g = guard(fetch_good, checks=lambda res, ctx: ["PASS"], policy=POLICY,
              on_decision=broken_consumer)
    check("a broken on_decision consumer still returns the result",
          g(), {"bars": 5})

    try:
        guard(fetch_raises, checks=lambda res, ctx: ["PASS"],
              policy=POLICY)()
        FAILURES.append("wrapped call's own exception was swallowed")
        print("  FAIL  the wrapped call's own exception propagates untouched")
    except Boom:
        print("  ok    the wrapped call's own exception propagates untouched")

    print("\nEnforce mode gates, and its own failure is a stated choice\n")

    g = guard(fetch_good, checks=lambda res, ctx: ["PASS"], policy=POLICY,
              mode=ENFORCE, on_decision=on_decision)
    check("a permitted call passes through in enforce", g(), {"bars": 5})

    g = guard(fetch_good, checks=lambda res, ctx: ["FAIL_UNSAFE"],
              policy=POLICY, mode=ENFORCE)
    try:
        g()
        FAILURES.append("enforce did not block a failing verdict")
        print("  FAIL  a failing verdict raises Blocked in enforce")
    except Blocked as e:
        print("  ok    a failing verdict raises Blocked in enforce")
        check("and the exception carries the decision",
              e.decision["decision"], BLOCK)

    g = guard(fetch_good, checks=lambda res, ctx: 1 / 0, policy=POLICY,
              mode=ENFORCE)  # on_gateway_error defaults to block
    try:
        g()
        FAILURES.append("gateway failure in enforce mode allowed the call")
        print("  FAIL  gateway failure blocks by default in enforce")
    except Blocked:
        print("  ok    gateway failure blocks by default in enforce")

    g = guard(fetch_good, checks=lambda res, ctx: 1 / 0, policy=POLICY,
              mode=ENFORCE, on_gateway_error="allow", on_decision=on_decision)
    check("with on_gateway_error='allow', stated in advance, it allows",
          g(), {"bars": 5})
    check("while still reporting the error decision",
          log[-1][0]["reasons"][0]["code"], "GATEWAY_ERROR")

    print("\nRefusals at wrap time, not call time\n")
    for label, kwargs in [
        ("an invalid mode", dict(mode="audit")),
        ("an invalid on_gateway_error", dict(on_gateway_error="shrug")),
    ]:
        try:
            guard(fetch_good, checks=lambda res, ctx: ["PASS"],
                  policy=POLICY, **kwargs)
            FAILURES.append(f"{label} was accepted")
            print(f"  FAIL  {label} is refused")
        except ValueError:
            print(f"  ok    {label} is refused")
    try:
        guard(fetch_good, checks=lambda r, c: ["PASS"],
              policy={"id": "bad", "version": 1,
                      "on_evidence": {EV_PASS: PERMIT}})
        FAILURES.append("an incomplete policy was accepted at wrap time")
        print("  FAIL  an incomplete policy is refused at wrap time")
    except Exception:  # noqa: BLE001
        print("  ok    an incomplete policy is refused at wrap time")

    print("\nReceipts chain across calls\n")
    log.clear()
    g = guard(fetch_good, checks=lambda res, ctx: ["PASS"], policy=POLICY,
              on_decision=on_decision)
    g(); g()
    check("second receipt links to the first",
          log[1][1]["chain"]["previous_receipt_hash"],
          log[0][1]["receipt_hash"])

    print()
    if FAILURES:
        print(f"{len(FAILURES)} failed:")
        for f in FAILURES:
            print("  " + f)
        return 1
    print("all wrapper checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
