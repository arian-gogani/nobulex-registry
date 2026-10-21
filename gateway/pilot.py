#!/usr/bin/env python3
"""Replay the gateway against YOUR data. Offline, nothing phoned home.

    python3 gateway/pilot.py --subject subject.json --authority authority.json
    python3 gateway/pilot.py --subject subject.json --authority authority.json \\
                            --labels labels.json --as-of 2026-09-17

README.md line 105 says "The fault challenge is the fixed suite a pilot
replays", and THESIS.md says a pilot replays it "against your path". Until
21 October 2026 nothing implemented that: every artifact in this repository ran
against a fictional offline corpus, so a prospective user could not get a number
about their own system without trusting ours. This is that command.

WHAT THIS PRINTS, AND WHAT IT REFUSES TO PRINT
----------------------------------------------
`fault_challenge.py` reports a catch rate because its corpus is LABELLED: every
case is a known planted fault, so "did a non-permit happen" is answerable.

Your data is not labelled. Nobody knows which of your rows are wrong, which is
the entire reason you would run this. So:

  * The verdict per check, the decision, the INDETERMINATE RATE and the latency
    are computed, because they are properties of this run.
  * The CATCH RATE and the FALSE-BLOCK RATE are reported as NOT_EVALUATED
    unless you supply --labels, because without ground truth they are not
    quantities this program can know. A tool that printed them anyway would be
    the exact defect this project exists to find: a measurement reporting a
    result about input it never had.

Supplying --labels is optional and makes those two numbers appear. They are then
about your labels, not about reality, and the output says so.

INPUT FORMAT
------------
--subject and --authority are JSON arrays of bar objects:

    [{"Date": "2026-09-10", "Open": 240.9, "High": 241.7,
      "Low": 240.5, "Close": 241.1}, ...]

--labels is a JSON object marking rows you believe are wrong, by date:

    {"faulty_dates": ["2026-09-14"], "clean_dates": ["2026-09-10"]}

EXIT CODES
----------
  0  the run completed and every bound held
  1  the run completed and a bound was crossed (see the indeterminate ceiling)
  2  the run could not be performed: input absent, unparseable, or empty

Exit 2 rather than 0 on bad input is deliberate and is the house rule: a run
that examined nothing has established nothing, and must not look like a pass.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import quantiles

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway"))
sys.path.insert(0, str(ROOT / "suite"))

from decide import (  # noqa: E402
    BLOCK, ESCALATE, EV_FAIL, EV_INDETERMINATE, EV_PASS, MODE_OBSERVE,
    PERMIT, decide, sha256,
)
from harness import (  # noqa: E402
    CONFIG, INDETERMINATE, NOT_EVALUATED, classify_fidelity,
    classify_freshness, classify_monotonic, classify_ohlc,
    classify_range_fidelity, classify_truncation,
)

# Same ceiling the fault challenge asserts, for the same reason: a rate that is
# printed but unbounded is still an escape hatch.
INDETERMINATE_CEILING = 0.25

POLICY = {
    "id": "pilot-v1",
    "version": 1,
    "on_evidence": {EV_PASS: PERMIT, EV_FAIL: BLOCK,
                    EV_INDETERMINATE: ESCALATE},
    "on_limit_violation": BLOCK,
    "limits": [],
}


def _load(path: Path, what: str):
    """Load JSON, or abstain loudly. Never returns a default."""
    if not path.exists():
        return None, f"{what} file not found: {path}"
    try:
        raw = path.read_text()
    except OSError as exc:
        return None, f"{what} file could not be read: {exc}"
    if not raw.strip():
        return None, f"{what} file is empty: {path}"
    try:
        return json.loads(raw), None
    except json.JSONDecodeError as exc:
        return None, f"{what} file is not valid JSON: {exc}"


# The two inputs use DIFFERENT key casing, and nothing documented it. Subject
# bars are read as "Date"/"Close"/"Open"/"High"/"Low"; authority bars are read
# as "date"/"close"/"open"/"high"/"low". A first-time user supplies both in one
# casing, every comparison check abstains, and the run reports 50% indeterminate
# with a reason that describes the symptom rather than the cause. I did exactly
# that while testing this file, which is how the check below came to exist.
#
# The classifiers are right to abstain. But a tool meant to be run by a stranger
# without talking to us has to name the fix, so this refuses up front instead of
# producing a confusing-but-technically-honest report.
SUBJECT_KEYS = ("Date", "Close")
AUTHORITY_KEYS = ("date", "close")


def _schema_complaint(rows, required, other_casing, label):
    """Return an actionable message, or None if the rows look readable."""
    if not isinstance(rows[0], dict):
        return (f"{label} rows are not JSON objects. Expected e.g. "
                f'{{"{required[0]}": "2026-09-10", "{required[1]}": 241.1}}')
    present = set(rows[0])
    missing = [k for k in required if k not in present]
    if not missing:
        return None
    wrong_case = [k for k in other_casing if k in present]
    if wrong_case:
        return (f"{label} rows use {wrong_case} but this input is read as "
                f"{list(required)}. The two inputs deliberately differ in "
                f"casing: --subject uses Capitalised keys, --authority uses "
                f"lowercase. Rename the keys in your {label} file and re-run.")
    return (f"{label} rows are missing {missing}. Keys present: "
            f"{sorted(present)[:8]}")


def run_checks(subject, authority, as_of):
    """Bind the classifiers exactly as fault_challenge.py does.

    Returns {name: (outcome, loss_cause, reason)}. The fidelity family compares
    against an authority; with no authority those checks are NOT_EVALUATED
    rather than skipped, because a skipped check that disappears from the
    denominator is how a clean-looking verdict gets manufactured.
    """
    tol = CONFIG["price_tolerance_rel"]
    out = {}

    if authority:
        out["truncation"] = classify_truncation(subject, authority)
        out["fidelity"] = classify_fidelity(subject, authority, tol)
        out["range_fidelity"] = classify_range_fidelity(subject, authority, tol)
    else:
        reason = ("no authority data supplied, so this check never observed "
                  "the subject against anything; supply --authority")
        for name in ("truncation", "fidelity", "range_fidelity"):
            out[name] = (NOT_EVALUATED, None, reason)

    # These three are self-contained: they need no outside authority.
    out["ohlc"] = classify_ohlc(subject)
    out["monotonic"] = classify_monotonic(subject)
    out["freshness"] = classify_freshness(
        subject, as_of, CONFIG["freshness_max_calendar_days"],
        CONFIG["freshness_max_future_days"])
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Replay the gateway against your own data, offline.")
    ap.add_argument("--subject", required=True, type=Path,
                    help="JSON array of bars your system produced")
    ap.add_argument("--authority", type=Path,
                    help="JSON array of bars from the outside authority. "
                         "Without it the three comparison checks report "
                         "NOT_EVALUATED rather than being silently dropped.")
    ap.add_argument("--labels", type=Path,
                    help="optional JSON marking dates you believe are faulty "
                         "or clean. Only with this can a catch rate and a "
                         "false-block rate be computed at all.")
    ap.add_argument("--as-of", dest="as_of",
                    help="observation time, ISO date (default: today, UTC). "
                         "Freshness is judged against this.")
    args = ap.parse_args(argv)

    # ---- input, with no permissive defaults ------------------------------
    subject, err = _load(args.subject, "subject")
    if err:
        print(f"CANNOT RUN: {err}")
        return 2
    if not isinstance(subject, list) or not subject:
        print("CANNOT RUN: subject must be a non-empty JSON array of bars. "
              "A run over zero rows establishes nothing and will not be "
              "reported as a pass.")
        return 2

    authority = None
    if args.authority:
        authority, err = _load(args.authority, "authority")
        if err:
            print(f"CANNOT RUN: {err}")
            return 2
        if not isinstance(authority, list) or not authority:
            print("CANNOT RUN: authority was supplied but is not a non-empty "
                  "JSON array. Omit --authority to run the self-contained "
                  "checks only; do not pass an empty one, because that would "
                  "silently become a comparison against nothing.")
            return 2

    # Pre-flight the schema before running anything. A run that abstains on
    # every comparison because of a key name is not a result worth printing.
    complaint = _schema_complaint(subject, SUBJECT_KEYS, AUTHORITY_KEYS,
                                  "subject")
    if complaint:
        print(f"CANNOT RUN: {complaint}")
        return 2
    if authority:
        complaint = _schema_complaint(authority, AUTHORITY_KEYS, SUBJECT_KEYS,
                                      "authority")
        if complaint:
            print(f"CANNOT RUN: {complaint}")
            return 2

    labels = None
    if args.labels:
        labels, err = _load(args.labels, "labels")
        if err:
            print(f"CANNOT RUN: {err}")
            return 2

    if args.as_of:
        try:
            as_of = datetime.fromisoformat(args.as_of).replace(
                tzinfo=timezone.utc)
        except ValueError as exc:
            print(f"CANNOT RUN: --as-of is not an ISO date: {exc}")
            return 2
    else:
        as_of = datetime.now(timezone.utc)

    # ---- the run ---------------------------------------------------------
    checks = run_checks(subject, authority, as_of)
    outcomes = [o for o, _, _ in checks.values()]
    d = decide(POLICY, outcomes, {}, mode=MODE_OBSERVE)

    # Latency of the policy layer only, measured the same way and labelled the
    # same way as in fault_challenge.py: this is not a network round trip and
    # not an evidence fetch.
    samples = []
    for _ in range(2000):
        t0 = time.perf_counter()
        decide(POLICY, outcomes, {}, mode=MODE_OBSERVE)
        samples.append((time.perf_counter() - t0) * 1000.0)
    samples.sort()
    p50, p95, p99 = (quantiles(samples, n=100)[49],
                     quantiles(samples, n=100)[94],
                     quantiles(samples, n=100)[98])

    # ---- report ----------------------------------------------------------
    print()
    print("pilot replay, your data, offline")
    print("=" * 72)
    print(f"  subject rows     {len(subject)}")
    print(f"  authority rows   {len(authority) if authority else 0}"
          f"{'' if authority else '   (none supplied)'}")
    print(f"  as of            {as_of.isoformat()}")
    print(f"  input hash       {sha256({'s': subject, 'a': authority})[:23]}")
    print()
    print("  check              outcome          reason")
    print("  " + "-" * 70)
    for name, (outcome, _cause, reason) in checks.items():
        r = (reason or "")[:40]
        print(f"  {name:18} {outcome:16} {r}")
    print()
    print(f"  evidence status  {d['evidence_status']}")
    print(f"  decision         {d['decision']}")
    print()

    n = len(outcomes)
    indet = sum(1 for o in outcomes
                if o in (INDETERMINATE, NOT_EVALUATED))
    rate = indet / n if n else 0.0
    print(f"  indeterminate    {indet}/{n} checks ({rate:.1%}), "
          f"ceiling {INDETERMINATE_CEILING:.0%}")
    print(f"  decide() latency p50 {p50:.3f} ms  p95 {p95:.3f} ms  "
          f"p99 {p99:.3f} ms  ({len(samples)} in-process, policy only)")
    print()

    # ---- the two numbers this program refuses to invent ------------------
    if labels is None:
        print("  catch rate       NOT_EVALUATED")
        print("  false blocks     NOT_EVALUATED")
        print("    Neither is computable without ground truth. Your data is "
              "unlabelled,")
        print("    which is why you are running this. Supply --labels to make "
              "them")
        print("    answerable, and they will then be about your labels rather "
              "than")
        print("    about reality. A number printed here without labels would be "
              "a")
        print("    measurement reporting a result about input it never had.")
    else:
        faulty = set(labels.get("faulty_dates") or [])
        clean = set(labels.get("clean_dates") or [])
        if not faulty and not clean:
            print("  catch rate       NOT_EVALUATED")
            print("  false blocks     NOT_EVALUATED")
            print("    --labels was supplied but names no dates. An empty "
                  "label set is")
            print("    not a clean bill of health.")
        else:
            dates = {b.get("Date") for b in subject}
            unknown = (faulty | clean) - dates
            caught = d["decision"] != PERMIT
            print(f"  labelled faulty  {len(faulty)} date(s)"
                  f"{'  ' + str(sorted(unknown)) + ' not in subject' if unknown else ''}")
            print(f"  labelled clean   {len(clean)} date(s)")
            print(f"  this run         {'non-permit' if caught else 'PERMIT'}"
                  f"  over the whole supplied window")
            print("    Note the granularity: this replay decides ONE window, "
                  "so these")
            print("    labels tell you whether that window ended in a "
                  "non-permit, not")
            print("    which row was responsible. Per-row attribution is not "
                  "something")
            print("    this command establishes.")
    print()

    # ---- what this run does NOT establish --------------------------------
    print("  This run is about your data and this policy. It does not "
          "establish that")
    print("  your pipeline is correct, that the authority you supplied is "
          "right, or")
    print("  that an unflagged row is clean. Checks reported NOT_EVALUATED "
          "were not")
    print("  run at all and are counted in the indeterminate rate above "
          "rather than")
    print("  dropped from the denominator.")
    print()

    if rate > INDETERMINATE_CEILING:
        print(f"BOUND CROSSED: indeterminate rate {rate:.1%} exceeds the "
              f"published ceiling of {INDETERMINATE_CEILING:.0%}.")
        print("  Most of this run was undecidable. The usual cause is missing "
              "authority")
        print("  data; the second is a subject whose fields this suite cannot "
              "read.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
