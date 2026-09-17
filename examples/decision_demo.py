#!/usr/bin/env python3
"""The three decisions shown on nobulex.com, produced by the real evaluator.

    python3 examples/decision_demo.py

Fictional inputs. No market-data provider is contacted and no order is
placed. What is real is the decision logic: this calls the same
gateway/decide.py the tests cover, so the outcomes below are computed, not
written down.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway"))
sys.path.insert(0, str(ROOT / "suite"))

from decide import (  # noqa: E402
    BLOCK, ESCALATE, EV_FAIL, EV_INDETERMINATE, EV_PASS, MODE_OBSERVE,
    PERMIT, decide, receipt, sha256,
)
from harness import FAIL_SAFE, FAIL_UNSAFE, PASS  # noqa: E402

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
        {"field": "evidence.quote.deviation_bps", "op": "lte", "value": 10,
         "code": "REFERENCE_CONSENSUS"},
    ],
}

CASES = [
    (
        "Fresh quote, within policy",
        [PASS],
        {"action": {"notional_usd": 24130},
         "evidence": {"quote": {"age_ms": 84, "deviation_bps": 2.1}}},
        "A 100 share order. Quote 84ms old, two references agree to 2.1bps.",
    ),
    (
        "Valid JSON, stale price",
        [FAIL_UNSAFE],
        {"action": {"notional_usd": 241110},
         "evidence": {"quote": {"age_ms": 862304, "deviation_bps": 81.0}}},
        "200 OK, schema valid, every field present. Price 14m 22s old and "
        "both references disagree by 81bps.",
    ),
    (
        "Truth cannot be established",
        [FAIL_SAFE],
        {"action": {"notional_usd": 92000},
         "evidence": {"quote": {"age_ms": 120}}},
        "Security halted, and a split leaves the adjusted basis unresolved. "
        "Note deviation_bps is absent, so that limit cannot be evaluated.",
    ),
]


def main():
    print(__doc__.strip().split("\n\n", 1)[1])
    print()
    print(f"Policy {POLICY['id']} v{POLICY['version']}  "
          f"mode={MODE_OBSERVE}  ({sha256(POLICY)[:23]}...)")
    print()

    previous = None
    for label, outcomes, context, note in CASES:
        d = decide(POLICY, outcomes, context, mode=MODE_OBSERVE)
        action = {"type": "broker.order.create", **context["action"]}
        refs = [{"type": "market.quote", "source_id": "primary",
                 "content_hash": sha256(context["evidence"])}]
        r = receipt(d, action, refs, previous_hash=previous)
        previous = r["receipt_hash"]

        print(f"── {label}")
        print(f"   {note}")
        print(f"   evidence_status : {d['evidence_status']}")
        print(f"   decision        : {d['decision']}")
        print(f"   would_block     : {d['would_block']}   "
              f"enforced: {d['enforced']}")
        if d["unevaluated_limits"]:
            print(f"   unevaluated     : {d['unevaluated_limits']} "
                  f"limit(s) could not be evaluated, which is not satisfied")
        for reason in d["reasons"]:
            if reason["status"] != "SATISFIED":
                detail = reason.get("detail")
                if detail:
                    print(f"   - {reason['code']}: {reason['status']}, {detail}")
                else:
                    print(f"   - {reason['code']}: {reason['status']}, "
                          f"observed {reason['observed']} "
                          f"{reason['op']} {reason['limit']}")
        print(f"   receipt         : {r['receipt_hash'][:27]}... "
              f"[{r['signature']['status']}]")
        print()

    print("Observe mode. Nothing was blocked, because nothing was routed "
          "through this. would_block is what enforcement would have done.")
    print("Receipts here are UNSIGNED: no key was supplied, and an unsigned "
          "receipt says so rather than looking signed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
