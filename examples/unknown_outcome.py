#!/usr/bin/env python3
"""A real defect found in this repository, reproduced before and after the fix.

    python3 examples/unknown_outcome.py

This is a worked example with no customer in it, which is the only honest kind
available while there are no customers. The defect is not hypothetical and was
not found in someone else's code: it was here, in the function every verdict in
this project passes through, and it survived 395 suite cases plus
seventeen self-test files.

THE DEFECT, stated plainly
--------------------------
`aggregate()` collapsed many per-probe outcomes into one. It walked a fixed
precedence order and returned the first member it found present. An outcome that
was not in that order was therefore never looked at: not rejected, not flagged,
simply invisible.

So one unreadable outcome beside one pass aggregated to PASS, and the gateway
turned PASS into PERMIT. A check that returned something the suite could not
interpret made no difference to the decision, which is the precise opposite of
what an unreadable check should do.

It was found on 21 October 2026 while fixing a narrower symptom: NOT_EVALUATED,
a sixth outcome this project defines and emits itself, was missing from the
gateway's evidence map. Adding it fixed the case where the strange outcome was
alone and left this one standing, because the drop happened one layer lower.

WHAT THIS SCRIPT SHOWS
----------------------
The fixed behaviour, and the old behaviour reproduced in-process so a reader can
see both without checking out an old commit. The "before" column is computed by
the original algorithm, included below verbatim as `aggregate_before`, not
described in prose.

Each row also shows the DECISION, because the aggregate value alone understates
it: PASS is not just a label, it is a permit to execute a financial action.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "suite"))
sys.path.insert(0, str(ROOT / "gateway"))

from harness import (  # noqa: E402
    FAIL_SAFE, FAIL_UNSAFE, INDETERMINATE, NOT_EVALUATED, OUT_OF_SCOPE, PASS,
    aggregate,
)
from decide import (  # noqa: E402
    BLOCK, ESCALATE, EV_FAIL, EV_INDETERMINATE, EV_PASS, MODE_OBSERVE, PERMIT,
    decide,
)

# The precedence order, as it was and still is.
_ORDER_BEFORE = [FAIL_UNSAFE, FAIL_SAFE, INDETERMINATE, NOT_EVALUATED, PASS,
                 OUT_OF_SCOPE]


def aggregate_before(outcomes):
    """The original, verbatim. Five lines, and the bug is the absence of a line.

    Nothing here is wrong about the outcomes it knows. The defect is that an
    outcome outside _ORDER_BEFORE is never compared against anything, so it
    cannot influence the result.
    """
    for o in _ORDER_BEFORE:
        if o in outcomes:
            return o
    return OUT_OF_SCOPE


POLICY = {
    "id": "example-unknown-outcome",
    "version": 1,
    "on_evidence": {EV_PASS: PERMIT, EV_FAIL: BLOCK,
                    EV_INDETERMINATE: ESCALATE},
    "on_limit_violation": BLOCK,
    "limits": [],
}


def decision_for(agg):
    """Run the real decision layer over one aggregate value."""
    try:
        return decide(POLICY, [agg], {}, mode=MODE_OBSERVE)["decision"]
    except Exception as exc:  # noqa: BLE001
        return f"RAISED {type(exc).__name__}"


def main():
    # "WAT" stands for any outcome this suite cannot interpret: a classifier
    # from a newer version, a typo in a binding, a plugin returning its own
    # vocabulary. The point is not the string, it is that nothing recognises it.
    cases = [
        # label, outcomes, expected aggregate NOW, expected decision NOW
        ("one pass, one unreadable outcome",
         [PASS, "WAT"], INDETERMINATE, ESCALATE),
        ("same thing, other argument order",
         ["WAT", PASS], INDETERMINATE, ESCALATE),
        ("two passes and one unreadable outcome",
         [PASS, PASS, "WAT"], INDETERMINATE, ESCALATE),
        ("an unreadable outcome on its own",
         ["WAT"], INDETERMINATE, ESCALATE),
        ("a quiet lie is still not softened by one",
         [FAIL_UNSAFE, "WAT"], FAIL_UNSAFE, BLOCK),
        ("an explicit refusal still escalates, not blocks",
         [FAIL_SAFE, "WAT"], FAIL_SAFE, ESCALATE),
        ("the sixth outcome this project emits itself",
         [NOT_EVALUATED], NOT_EVALUATED, ESCALATE),
        ("and a genuinely clean set still permits",
         [PASS, PASS], PASS, PERMIT),
    ]

    print()
    print("Fictional outcome sets passed to the real aggregate() and the real")
    print("decide(). No network, no live tool, no registry attestation.")
    print()
    print(f"  {'case':50} {'before':14} {'now':14} decision")
    print("  " + "-" * 104)

    errors = 0
    changed = 0
    for label, outcomes, want_agg, want_decision in cases:
        before = aggregate_before(list(outcomes))
        now = aggregate(list(outcomes))
        decision = decision_for(now)
        before_decision = decision_for(before)
        # Count a change only when the DECISION changed. aggregate() moving
        # from OUT_OF_SCOPE to INDETERMINATE is a vocabulary change that leaves
        # the decision identical, and counting it would overstate the fix.
        mark = ""
        if before_decision != decision:
            changed += 1
            mark = f"   <-- was {before_decision}"
        elif before != now:
            mark = "   (label only, same decision)"
        print(f"  {label:50} {before:14} {now:14} {decision}{mark}")
        if now != want_agg or decision != want_decision:
            errors += 1
            print(f"      DEMO CHECK FAILED: expected {want_agg} / "
                  f"{want_decision}", file=sys.stderr)

    print()
    if errors:
        print(f"{errors} case(s) did not reproduce. This script is wrong, or "
              f"the fix regressed.", file=sys.stderr)
        return 1

    print(f"{len(cases)}/{len(cases)} expected outcomes reproduced. "
          f"{changed} case(s) changed DECISION, each from PERMIT to ESCALATE.")
    print()
    print("Read the fifth and sixth rows before concluding the fix is blunt.")
    print("FAIL_UNSAFE still dominates and FAIL_SAFE still escalates rather")
    print("than blocking, so an unreadable outcome does not flatten the")
    print("vocabulary into one answer. It ranks where no-claim-was-established")
    print("already ranks, and nowhere worse.")
    print()
    print("WHAT THIS DOES NOT ESTABLISH. That the rest of this repository is")
    print("free of the same shape: this function was audited and green before")
    print("21 October. That any particular deployment hit it, which is not")
    print("knowable from here. Or that unknown outcomes are common; the reason")
    print("to fix it is that one is enough, and the failure direction was a")
    print("permit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
