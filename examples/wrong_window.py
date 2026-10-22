#!/usr/bin/env python3
"""Offline, fictional inputs passed to the real truncation classifier."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "suite"))
from harness import classify_truncation, PASS, FAIL_UNSAFE, INDETERMINATE


def main():
    dates = [f"2020-01-{day:02d}" for day in (6, 7, 8, 9, 10)]
    reference = [{"date": date, "close": 100.0} for date in dates]
    matching = [{"Date": date, "Close": 100.0} for date in dates]
    wrong_window = [
        {"Date": f"1999-01-{day:02d}", "Close": 100.0}
        for day in (4, 5, 6, 7, 8)
    ]
    cases = [
        ("Matching window", matching, (PASS, None)),
        ("Two sessions silently missing", matching[:3],
         (FAIL_UNSAFE, "partial_truncation")),
        # The cause slot carried None until 22 Oct 2026, when the 50
        # indeterminate sites in harness.py were closed to a published list.
        # "overlap_too_thin" is the right code here and says more than None did:
        # the two windows do not overlap enough to compare, which is a statement
        # about the alignment of the two sides rather than about either one.
        ("Same count, entirely different dates", wrong_window,
         (INDETERMINATE, "overlap_too_thin")),
    ]
    print("Fictional fixtures. No network, live tool, or registry attestation.\n")
    errors = 0
    for label, subject, expected in cases:
        outcome, cause, evidence = classify_truncation(subject, reference)
        print(label)
        print(f"  Count-only comparison: {len(subject) == len(reference)}")
        print(f"  Nobulex truncation probe: {outcome}")
        print(f"  Evidence: {evidence}\n")
        if (outcome, cause) != expected:
            errors += 1
            print(f"  DEMO CHECK FAILED: expected {expected!r}", file=sys.stderr)
    if errors:
        return 1
    print("3/3 expected outcomes reproduced.")
    print("PASS covers this probe only. It does not establish price correctness.")
    print("A different window is unresolved here, not a proven tool defect.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
