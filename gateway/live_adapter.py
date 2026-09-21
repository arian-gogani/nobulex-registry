#!/usr/bin/env python3
"""Bind a fetched price series to a real authority and a real decision.

    python3 gateway/live_adapter.py AAPL
    python3 gateway/live_adapter.py AAPL --inject stale
    python3 gateway/live_adapter.py AAPL --inject truncate

This is the first thing in the repository that touches a live source. It
fetches a daily series for one ticker from the same public endpoint the
suite uses as its authority, runs the real classifiers against the
authority's own answer, and puts the result through the real decision
layer. With no fault injected the subject IS the authority, so the honest
answer is PERMIT: the transport is faithful to itself. --inject corrupts
the fetched series in one specific, plausible way before it is judged, so
the same live pipeline can be shown catching a real-shaped defect on real
numbers.

What this proves and does not:

  It proves the pipeline runs against live data end to end, and that a
  corrupted live series is caught rather than permitted.

  It does NOT verify any third-party tool. The subject here is the
  authority's own series, optionally corrupted by this script. A real
  pilot points `subject_fetch` at the tool under test and keeps the
  authority independent. Where the only reference IS the subject's own
  upstream, a value verdict is OUT_OF_SCOPE, not PASS, exactly as the
  suite already documents.

  A network call reaches a third party. Nothing is sent about you; a
  ticker and a range go out to a public price endpoint.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway"))
sys.path.insert(0, str(ROOT / "suite"))

from decide import (  # noqa: E402
    BLOCK, ESCALATE, EV_FAIL, EV_INDETERMINATE, EV_PASS, MODE_OBSERVE, PERMIT,
    decide, receipt, sha256,
)
from harness import (  # noqa: E402
    CONFIG, AuthorityUnavailable, a1_chart, classify_fidelity,
    classify_range_fidelity, classify_freshness, classify_monotonic,
    classify_ohlc, classify_truncation,
)

POLICY = {
    "id": "live-equity-v1",
    "version": 1,
    "on_evidence": {EV_PASS: PERMIT, EV_FAIL: BLOCK,
                    EV_INDETERMINATE: ESCALATE},
    "on_limit_violation": BLOCK,
    "limits": [{"field": "action.notional_usd", "op": "lte", "value": 50000,
                "code": "POLICY_NOTIONAL_WITHIN_LIMIT"}],
}
CONTEXT = {"action": {"notional_usd": 10000}}


def authority_bars(ticker):
    """The authority's own daily series, as {date, close, open, high, low}.

    a1_chart already fetches all four; this used to keep only close, which
    meant classify_range_fidelity never had an authority to compare a
    subject's Open, High or Low against here, no matter what the subject
    reported. open/high/low are carried through now but not required: a
    session missing one is still usable for close-only comparison."""
    a = a1_chart(ticker, rng="1mo", interval="1d")
    return [{"date": b["date"], "close": b["close"], "open": b.get("open"),
             "high": b.get("high"), "low": b.get("low")}
            for b in a["bars"] if b.get("close") is not None]


def subject_from_authority(auth):
    """The subject, in the shape a tool would return it (Date/Close ...).

    Mirrors the authority's own Open, High and Low when present, rather than
    flattening all three to Close. A subject built by flattening can never
    disagree with the authority on range, which is exactly the blind spot
    classify_range_fidelity exists to close; a faithful subject has to carry
    the real numbers to be a faithful test of comparing them."""
    return [{"Date": b["date"], "Close": b["close"],
             "Open": b["open"] if b.get("open") is not None else b["close"],
             "High": b["high"] if b.get("high") is not None else b["close"],
             "Low": b["low"] if b.get("low") is not None else b["close"]}
            for b in auth]


def inject(subject, kind):
    """Corrupt a faithful subject in one plausible way, on real numbers."""
    if kind == "truncate":
        return subject[:max(1, len(subject) // 2)], (
            "dropped the second half of the series, no truncation signal")
    if kind == "stale":
        # Freeze the newest bar's value onto an old date, i.e. serve last
        # month while claiming today. Shift every date back one month.
        out = []
        for b in subject:
            d = datetime.strptime(b["Date"], "%Y-%m-%d")
            old = d.replace(year=d.year - 1).strftime("%Y-%m-%d")
            out.append({**b, "Date": old})
        return out, "shifted every session back a year, so the newest bar is stale"
    if kind == "corrupt":
        out = [dict(b) for b in subject]
        out[-1]["Close"] = round(out[-1]["Close"] * 1.02, 4)
        out[-1]["High"] = round(out[-1]["High"] * 1.02, 4)
        out[-1]["Low"] = round(out[-1]["Low"] * 1.02, 4)
        out[-1]["Open"] = round(out[-1]["Open"] * 1.02, 4)
        return out, "moved the most recent close 2% off the authority's value"
    if kind == "future":
        out = [dict(b) for b in subject]
        d = datetime.strptime(out[-1]["Date"], "%Y-%m-%d")
        out[-1]["Date"] = d.replace(year=d.year + 1).strftime("%Y-%m-%d")
        return out, "dated the newest bar a year ahead, observed by nobody"
    raise SystemExit(f"unknown injection {kind!r}; "
                     "choose truncate, stale, corrupt or future")


def run(subject, authority, now_utc, policy=POLICY, context=CONTEXT,
        mode=MODE_OBSERVE):
    """policy, context and mode default to this module's own, so the CLI is
    unaffected; the HTTP surface passes its own running policy and mode
    instead so a live check is judged the same way the gateway was
    actually started, not by a policy or mode baked into this file."""
    tol = CONFIG["price_tolerance_rel"]
    checks = {
        "truncation": classify_truncation(subject, authority),
        "fidelity": classify_fidelity(subject, authority, tol),
        "range_fidelity": classify_range_fidelity(subject, authority, tol),
        "ohlc": classify_ohlc(subject),
        "monotonic": classify_monotonic(subject),
        "freshness": classify_freshness(
            subject, now_utc, CONFIG["freshness_max_calendar_days"],
            CONFIG["freshness_max_future_days"]),
    }
    outcomes = [o for o, _, _ in checks.values()]
    d = decide(policy, outcomes, context, mode=mode)
    return checks, d


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("ticker")
    ap.add_argument("--inject", choices=["truncate", "stale", "corrupt",
                                         "future"])
    args = ap.parse_args()

    try:
        auth = authority_bars(args.ticker)
    except AuthorityUnavailable as e:
        # The authority not answering is INDETERMINATE, never a pass. Said
        # in the authority's own words, not a Python type.
        print(f"authority did not answer for {args.ticker}: {e}")
        print("evidence_status: INDETERMINATE  decision: ESCALATE  "
              "(no reference, so no verdict)")
        return 2
    if len(auth) < 2:
        print(f"authority returned {len(auth)} usable bars for {args.ticker}, "
              "not enough to compare")
        return 2

    subject = subject_from_authority(auth)
    note = "subject is the authority's own series, faithful transport"
    if args.inject:
        subject, note = inject(subject, args.inject)

    now_utc = datetime.now(timezone.utc)
    checks, d = run(subject, auth, now_utc)

    print(f"ticker {args.ticker}  authority yahoo-finance-chart-v8  "
          f"{len(auth)} sessions  latest {auth[-1]['date']} "
          f"{auth[-1]['close']:.2f}")
    print(f"subject: {note}")
    print(f"policy {POLICY['id']} ({sha256(POLICY)[:23]}...)\n")

    # 15, not 12: range_fidelity is 14 characters and silently broke the
    # column when it was added. Width is derived rather than pinned so the
    # next check to outgrow it does not do the same.
    w = max(15, *(len(n) for n in checks)) if checks else 15
    print(f"  {'check':{w}} {'verdict':14} evidence")
    for name, (outcome, cause, evidence) in checks.items():
        print(f"  {name:{w}} {outcome:14} {str(evidence)[:70]}")
    print()

    action = {"type": "broker.order.create", "symbol": args.ticker,
              "notional_usd": CONTEXT["action"]["notional_usd"]}
    refs = [{"type": "market.chart", "source_id": "yahoo-finance-chart-v8",
             "observed_at": now_utc.isoformat(),
             "content_hash": sha256(auth)}]
    r = receipt(d, action, refs)

    print(f"evidence_status : {d['evidence_status']}")
    print(f"decision        : {d['decision']}")
    print(f"would_block     : {d['would_block']}   enforced: {d['enforced']}")
    print(f"receipt         : {r['receipt_hash'][:27]}... "
          f"[{r['signature']['status']}]")
    print()

    if args.inject:
        if not d["would_block"]:
            print("EXPECTED A NON-PERMIT ON AN INJECTED FAULT. This is a "
                  "real problem, not a demo flourish.")
            return 1
        print(f"The injected {args.inject} fault was caught on live "
              f"{args.ticker} data: {d['decision']}.")
    else:
        print("No fault injected, so the subject equals the authority and "
              "the faithful-transport answer is PERMIT. Add --inject to see "
              "the same live pipeline catch a corrupted series.")
    print("\nThis run touched a live endpoint. The subject here is the "
          "authority's own series; it verifies the pipeline, not a "
          "third-party tool.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
