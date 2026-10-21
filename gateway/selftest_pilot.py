#!/usr/bin/env python3
"""Controls for gateway/pilot.py. Offline, writes only to a temp directory.

    python3 gateway/selftest_pilot.py

The pilot is the first artifact in this repository meant to be run by someone
who has not spoken to us, so the properties worth pinning are not only "does it
compute the right verdict" but "does it refuse in a way that tells the user what
to fix". Both are asserted here.

The load-bearing one is the NOT_EVALUATED pair. A pilot that printed a catch
rate over unlabelled customer data would be the exact defect this project
exists to find, and it would be the most tempting number to print.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "gateway" / "pilot.py"

FAILURES = []


def check(label, got, want):
    if got == want:
        print(f"  ok    {label}")
    else:
        FAILURES.append(f"{label}: got {got!r}, want {want!r}")
        print(f"  FAIL  {label}: got {got!r}, want {want!r}")


DATES = ["2026-09-10", "2026-09-11", "2026-09-14", "2026-09-15", "2026-09-16"]
CLOSES = [241.10, 242.05, 240.80, 243.00, 242.60]


def subject_bars(closes=None):
    closes = closes or CLOSES
    return [{"Date": d, "Open": round(c - 0.2, 2), "High": round(c + 0.6, 2),
             "Low": round(c - 0.6, 2), "Close": c}
            for d, c in zip(DATES, closes)]


def authority_bars(closes=None):
    """Lowercase keys. The casing difference is real; see pilot.py."""
    closes = closes or CLOSES
    return [{"date": d, "open": round(c - 0.2, 2), "high": round(c + 0.6, 2),
             "low": round(c - 0.6, 2), "close": c}
            for d, c in zip(DATES, closes)]


def run(tmp, **files):
    """Write the given fixtures and invoke the pilot. Returns (exit, output)."""
    args = [sys.executable, str(PILOT)]
    for flag, data in files.items():
        if data is None:
            continue
        p = Path(tmp) / f"{flag}.json"
        p.write_text(json.dumps(data))
        args += [f"--{flag}", str(p)]
    args += ["--as-of", "2026-09-17"]
    r = subprocess.run(args, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def main() -> int:
    print("pilot controls")
    print("=" * 72)

    with tempfile.TemporaryDirectory() as tmp:
        # --- the happy path, so every refusal below means something ---------
        code, out = run(tmp, subject=subject_bars(), authority=authority_bars())
        check("clean subject against matching authority exits 0", code, 0)
        check("and PERMITs", "decision         PERMIT" in out, True)
        check("with a 0% indeterminate rate",
              "indeterminate    0/6 checks (0.0%)" in out, True)

        # --- the defect it exists to catch ----------------------------------
        bad = subject_bars()
        bad[2]["Close"] = 255.00
        code, out = run(tmp, subject=bad, authority=authority_bars())
        check("a wrong close is FAIL_UNSAFE, not INDETERMINATE",
              "FAIL_UNSAFE" in out, True)
        check("and the decision is BLOCK", "decision         BLOCK" in out, True)
        check("and the reason quantifies the deviation",
              "deviates" in out, True)

        # --- THE LOAD-BEARING PAIR ------------------------------------------
        # Unlabelled data cannot yield a catch rate. This is the number a
        # vendor most wants to print and least has the right to.
        code, out = run(tmp, subject=subject_bars(), authority=authority_bars())
        check("catch rate over unlabelled data is NOT_EVALUATED",
              "catch rate       NOT_EVALUATED" in out, True)
        check("false-block rate over unlabelled data is NOT_EVALUATED",
              "false blocks     NOT_EVALUATED" in out, True)
        check("and no percentage is printed beside either",
              "catch rate       100" not in out and "catch rate       0.0%" not in out,
              True)

        # An empty label set is not a clean bill of health.
        code, out = run(tmp, subject=subject_bars(),
                        authority=authority_bars(),
                        labels={"faulty_dates": [], "clean_dates": []})
        check("an empty label set still yields NOT_EVALUATED",
              "catch rate       NOT_EVALUATED" in out, True)

        # With real labels the numbers may appear.
        code, out = run(tmp, subject=subject_bars(),
                        authority=authority_bars(),
                        labels={"faulty_dates": ["2026-09-14"],
                                "clean_dates": ["2026-09-10"]})
        check("labels make the comparison reportable",
              "labelled faulty  1 date(s)" in out, True)
        check("and the granularity limit is stated rather than implied",
              "not" in out and "which row was responsible" in out, True)

        # --- refusals that have to be actionable ----------------------------
        code, out = run(tmp, subject=subject_bars(), authority=subject_bars())
        check("authority in subject casing refuses rather than abstaining 50%",
              code, 2)
        check("and the message names the actual fix",
              "deliberately differ in casing" in out, True)

        code, out = run(tmp, subject=[], authority=authority_bars())
        check("an empty subject exits 2, never 0", code, 2)
        check("and says a run over zero rows establishes nothing",
              "establishes nothing" in out, True)

        code, out = run(tmp, subject=subject_bars(), authority=[])
        check("an empty authority exits 2 rather than comparing to nothing",
              code, 2)

        # Missing file, not just empty.
        r = subprocess.run(
            [sys.executable, str(PILOT), "--subject",
             str(Path(tmp) / "nope.json")],
            capture_output=True, text=True)
        check("an absent subject file exits 2", r.returncode, 2)

        # --- no authority at all: abstain, and COUNT the abstention ---------
        code, out = run(tmp, subject=subject_bars())
        check("without authority the comparison checks are NOT_EVALUATED",
              "NOT_EVALUATED" in out, True)
        check("the abstentions stay in the denominator (3 of 6, not 0 of 3)",
              "indeterminate    3/6 checks" in out, True)
        check("and crossing the ceiling exits 1, not 0", code, 1)
        check("naming the bound it crossed", "BOUND CROSSED" in out, True)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} failed:\n")
        for f in FAILURES:
            print("  " + f)
        return 1
    print("all pilot controls passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
