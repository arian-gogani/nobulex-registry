#!/usr/bin/env python3
"""The fault challenge: a fixed suite of well-formed-but-wrong conditions.

    python3 gateway/fault_challenge.py

Every fault here returns 200-shaped data: parseable, plausible, correctly
typed as far as a schema can see. Each is fed through the suite's real
classifiers and the result through the real decision layer, and three
numbers come out measured rather than claimed:

    catch rate        faults that end in a non-permit
    false-block rate  clean cases that end in anything but PERMIT
    decide() latency  policy evaluation only, in process

Honest scope, stated where it cannot be missed: the corpus is fictional and
offline. It exercises the classifiers and the decision layer, not any live
tool, feed or venue. Latency here is policy evaluation in process, not a
network round trip and not an evidence fetch. A pilot replays this same
corpus against a customer's real path, which is where the numbers become
about their system rather than ours.

The corpus is versioned and pinned by hash, so "a fixed suite" is a claim a
reader can check rather than take. The script asserts every expectation and
exits nonzero if any drifts.
"""

from __future__ import annotations

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
    CONFIG, classify_fidelity, classify_freshness, classify_monotonic,
    classify_ohlc, classify_truncation,
)

CORPUS_VERSION = "v1"

# A fixed observation time, so the corpus is deterministic and a re-run
# months from now reproduces byte-identical results.
AS_OF = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)

# Five sessions before AS_OF. 2026-09-12/13 are a weekend.
SESSIONS = ["2026-09-10", "2026-09-11", "2026-09-14", "2026-09-15", "2026-09-16"]
CLOSES = [241.10, 242.05, 240.80, 243.00, 242.60]

AUTHORITY = [{"date": d, "close": c} for d, c in zip(SESSIONS, CLOSES)]


def bars(dates=SESSIONS, closes=CLOSES, spread=0.6):
    """Well-formed subject bars: OHLC consistent, dates as given."""
    out = []
    for d, c in zip(dates, closes):
        out.append({"Date": d, "Open": round(c - 0.2, 2),
                    "High": round(c + spread, 2),
                    "Low": round(c - spread, 2), "Close": c})
    return out


def run_checks(subject):
    """Run every applicable classifier, the way a pilot binds them."""
    tol = CONFIG["price_tolerance_rel"]
    out = {}
    out["truncation"] = classify_truncation(subject, AUTHORITY)
    out["fidelity"] = classify_fidelity(subject, AUTHORITY, tol)
    out["ohlc"] = classify_ohlc(subject)
    out["monotonic"] = classify_monotonic(subject)
    out["freshness"] = classify_freshness(
        subject, AS_OF, CONFIG["freshness_max_calendar_days"],
        CONFIG["freshness_max_future_days"])
    return out


POLICY = {
    "id": "fault-challenge-v1",
    "version": 1,
    "on_evidence": {EV_PASS: PERMIT, EV_FAIL: BLOCK,
                    EV_INDETERMINATE: ESCALATE},
    "on_limit_violation": BLOCK,
    "limits": [{"field": "action.notional_usd", "op": "lte", "value": 50000,
                "code": "POLICY_NOTIONAL_WITHIN_LIMIT"}],
}
CONTEXT = {"action": {"notional_usd": 10000}}


def fault_cases():
    """(name, why it passes a schema check, subject bars, check expected to fire)."""
    nan = float("nan")
    return [
        ("silent_truncation",
         "three rows instead of five, no truncation signal anywhere",
         bars(SESSIONS[:3], CLOSES[:3]), "truncation"),

        ("empty_result",
         "an empty list where five sessions exist, which validates cleanly",
         [], "truncation"),

        ("wrong_window",
         "five rows, right count, entirely different year",
         bars([f"1999-01-{d:02d}" for d in (4, 5, 6, 7, 8)]), "truncation"),

        ("stale_series",
         "a complete series whose newest bar is twelve days old",
         bars(["2026-08-31", "2026-09-01", "2026-09-02",
               "2026-09-03", "2026-09-04"]), "freshness"),

        ("future_bar",
         "a bar dated eight days ahead, observed by nobody",
         bars(SESSIONS[:4] + ["2026-09-25"]), "freshness"),

        ("ohlc_violation",
         "a High below its own Close, numerically typed and plausible",
         bars()[:4] + [{"Date": SESSIONS[4], "Open": 242.4, "High": 239.0,
                        "Low": 238.0, "Close": 242.60}], "ohlc"),

        ("string_prices",
         "prices as strings; classify_ohlc gates on numeric type before "
         "comparing, so this is unreadable rather than a string comparison "
         "quietly returning a wrong-but-plausible answer",
         [{"Date": d, "Open": str(c - 0.2), "High": str(c + 0.6),
           "Low": str(c - 0.6), "Close": str(c)}
          for d, c in zip(SESSIONS, CLOSES)], "ohlc"),

        ("nonmonotonic_dates",
         "two sessions swapped, every row individually valid",
         bars([SESSIONS[0], SESSIONS[2], SESSIONS[1],
               SESSIONS[3], SESSIONS[4]]), "monotonic"),

        ("value_corruption",
         "every close off by one percent against the same upstream",
         bars(SESSIONS, [round(c * 1.01, 2) for c in CLOSES]), "fidelity"),

        ("split_basis_mix",
         "closes on the unadjusted basis, exactly half the authority's",
         bars(SESSIONS, [round(c * 0.5, 2) for c in CLOSES]), "fidelity"),

        ("nan_closes",
         "the bare token NaN, which json.loads accepts off the wire",
         [{"Date": d, "Open": c, "High": c, "Low": c, "Close": nan}
          for d, c in zip(SESSIONS, CLOSES)], "fidelity"),
    ]


def clean_cases():
    extra = [dict(b, Volume=1_000_000, AdjClose=b["Close"]) for b in bars()]
    return [
        ("exact_match", "byte-identical closes on identical sessions", bars()),
        ("rounding_drift",
         "two basis points of drift, inside the five the policy pins",
         bars(SESSIONS, [round(c * 1.0002, 2) for c in CLOSES])),
        ("extra_fields",
         "unknown extra keys on every bar, which must be ignored, not feared",
         extra),
    ]


def main():
    corpus_hash = sha256({"version": CORPUS_VERSION, "as_of": AS_OF.isoformat(),
                          "sessions": SESSIONS, "closes": CLOSES})
    print(f"fault challenge {CORPUS_VERSION}  corpus {corpus_hash[:23]}...")
    print(f"observation time pinned at {AS_OF.isoformat()}  "
          f"policy {POLICY['id']} ({sha256(POLICY)[:23]}...)\n")

    failures = []
    caught = 0
    faults = fault_cases()

    print(f"{'fault':22} {'fired':34} {'evidence':13} decision")
    print("-" * 78)
    for name, why, subject, expected_check in faults:
        checks = run_checks(subject)
        outcomes = [o for o, _, _ in checks.values()]
        d = decide(POLICY, outcomes, CONTEXT, mode=MODE_OBSERVE)

        fired = [k for k, (o, _, _) in checks.items() if o != "PASS"]
        exp_outcome = checks[expected_check][0]
        if exp_outcome == "PASS":
            failures.append(f"{name}: expected {expected_check} to fire, it passed")
        if not d["would_block"]:
            failures.append(f"{name}: reached {d['decision']}, a fault must never permit")
        else:
            caught += 1
        print(f"{name:22} {','.join(fired)[:34]:34} "
              f"{d['evidence_status']:13} {d['decision']}")

    print()
    # Degraded evidence: not a fault in the subject, not clean either. The
    # authority itself carries a null close, so one session of the comparison
    # is unreadable. The method's rule is that a comparison is only as
    # readable as its weaker half, so this must ESCALATE. Permitting it would
    # treat unmeasured as measured-and-fine; blocking it would fail a subject
    # for its judge's gap. First written as a clean case here, and the suite
    # refused to permit it, which is the suite being right about its own rule.
    auth_with_null = [dict(b) for b in AUTHORITY]
    auth_with_null[2]["close"] = None
    tol = CONFIG["price_tolerance_rel"]
    subject = bars()
    checks = {
        "truncation": classify_truncation(subject, auth_with_null),
        "fidelity": classify_fidelity(subject, auth_with_null, tol),
        "ohlc": classify_ohlc(subject),
        "monotonic": classify_monotonic(subject),
        "freshness": classify_freshness(
            subject, AS_OF, CONFIG["freshness_max_calendar_days"],
            CONFIG["freshness_max_future_days"]),
    }
    d = decide(POLICY, [o for o, _, _ in checks.values()], CONTEXT,
               mode=MODE_OBSERVE)
    print(f"{'degraded: authority_null_close':38} {'':18} "
          f"{d['evidence_status']:13} {d['decision']}")
    if d["decision"] != ESCALATE:
        failures.append(
            f"authority_null_close must ESCALATE, got {d['decision']}. "
            "Permit treats unmeasured as fine; block blames the subject "
            "for its judge's gap.")

    print()
    cleans = clean_cases()
    permitted = 0
    for name, why, subject in cleans:
        checks = run_checks(subject)
        outcomes = [o for o, _, _ in checks.values()]
        d = decide(POLICY, outcomes, CONTEXT, mode=MODE_OBSERVE)
        ok = d["decision"] == PERMIT
        permitted += ok
        if not ok:
            fired = {k: v[0] for k, v in checks.items() if v[0] != "PASS"}
            failures.append(f"clean case {name} was not permitted: {fired}")
        print(f"{'clean: ' + name:38} {'':18} "
              f"{d['evidence_status']:13} {d['decision']}")

    # Latency of the decision layer itself, in process. Not a network number
    # and not an evidence fetch, and labelled so.
    outcomes = ["PASS"] * 5
    n = 2000
    samples = []
    for _ in range(n):
        t0 = time.perf_counter()
        decide(POLICY, outcomes, CONTEXT, mode=MODE_OBSERVE)
        samples.append((time.perf_counter() - t0) * 1000.0)
    qs = quantiles(samples, n=100)
    p50, p95, p99 = qs[49], qs[94], qs[98]

    print()
    print(f"catch rate        {caught}/{len(faults)} faults ended in a non-permit")
    print(f"false blocks      {len(cleans) - permitted}/{len(cleans)} clean cases")
    print(f"decide() latency  p50 {p50:.3f} ms  p95 {p95:.3f} ms  p99 {p99:.3f} ms"
          f"  ({n} in-process evaluations, policy only)")
    print()

    if failures:
        print(f"{len(failures)} expectation(s) violated:")
        for f in failures:
            print("  " + f)
        return 1
    print("every fault was caught, every clean case permitted, and this "
          "script exits nonzero the day either stops being true.")
    print("Fictional corpus, offline. A pilot replays it against your path; "
          "that run's numbers are about your system, not this one.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
