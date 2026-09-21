#!/usr/bin/env python3
"""Tests for the live adapter, with no network dependency.

The adapter reaches a live endpoint. Its tests must not, or a suite that is
supposed to run anywhere becomes a suite that fails on a plane. So the
network boundary is stubbed with a fixed authority series, and everything
below the fetch, the injections and the decision logic, is exercised for
real against it.

    python3 gateway/selftest_live.py
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "suite"))

from decide import PERMIT  # noqa: E402
import live_adapter as la  # noqa: E402

FAILURES = []


def check(label, got, want):
    if got != want:
        FAILURES.append(f"{label}: got {got!r}, want {want!r}")
        print(f"  FAIL  {label}")
    else:
        print(f"  ok    {label}")


# A fixed authority series ending "today" from the test's point of view, so
# the freshness classifier sees a current newest bar without a network call.
NOW = datetime(2026, 9, 17, 20, 0, tzinfo=timezone.utc)
DATES = ["2026-08-31", "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04",
         "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11", "2026-09-14",
         "2026-09-15", "2026-09-16", "2026-09-17"]
CLOSES = [330.0 + i * 0.4 for i in range(len(DATES))]
# open/high/low are real and distinct from close, not copies of it, so a
# faithful subject built from this authority actually exercises
# classify_range_fidelity's comparison rather than trivially matching itself.
AUTH = [{"date": d, "close": round(c, 2), "open": round(c - 0.3, 2),
        "high": round(c + 0.7, 2), "low": round(c - 0.6, 2)}
        for d, c in zip(DATES, CLOSES)]


def main():
    print("Faithful transport permits on a fixed authority\n")
    subject = la.subject_from_authority(AUTH)
    checks, d = la.run(subject, AUTH, NOW)
    check("a faithful subject is all PASS",
          all(o == "PASS" for o, _, _ in checks.values()), True)
    check("and permits", d["decision"], PERMIT)
    check("and does not claim a block", d["would_block"], False)

    print("\nEvery injection is a non-permit, and by the right classifier\n")
    expect = {
        "truncate": "truncation",
        "stale": "freshness",
        "corrupt": "fidelity",
        "future": "freshness",
    }
    for kind, culprit in expect.items():
        corrupted, note = la.inject(la.subject_from_authority(AUTH), kind)
        checks, d = la.run(corrupted, AUTH, NOW)
        check(f"{kind} is not permitted", d["would_block"], True)
        check(f"{kind} is caught by {culprit}",
              checks[culprit][0] in ("FAIL_UNSAFE", "INDETERMINATE"), True)
        check(f"{kind} has a human-readable note", bool(note), True)

    print("\nThe corrupt case names the deviation it found\n")
    corrupted, _ = la.inject(la.subject_from_authority(AUTH), "corrupt")
    checks, _ = la.run(corrupted, AUTH, NOW)
    _, _, evidence = checks["fidelity"]
    check("the fidelity evidence mentions a percentage",
          "%" in str(evidence), True)
    check("and names the deviating session",
          DATES[-1] in str(evidence), True)

    print("\nAn unknown injection is refused, not silently applied\n")
    try:
        la.inject(la.subject_from_authority(AUTH), "smudge")
        FAILURES.append("an unknown injection was silently accepted")
        print("  FAIL  an unknown injection is refused")
    except SystemExit:
        print("  ok    an unknown injection is refused")

    print()
    if FAILURES:
        print(f"{len(FAILURES)} failed:")
        for f in FAILURES:
            print("  " + f)
        return 1
    print("all live-adapter checks passed, no network required")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
