#!/usr/bin/env python3
"""
Nobulex reliability suite v0.1 -- harness selftest.

WHAT THIS IS FOR
----------------
A harness that has never caught a planted bug has not been tested. Every
classifier in harness.py claims to detect a specific failure. This file feeds
each one a fixture where that failure is planted deliberately, and asserts the
exact (outcome, loss_cause) pair comes back.

It also feeds each one a clean fixture and asserts it does NOT fire. A
classifier that returns FAIL_UNSAFE for every input detects nothing; it just
has a stuck needle. Both halves are required.

No network. No subprocess. The classifiers are pure, which is the entire
reason this file can exist.

Exit code 0 only if every case passes. Anything else means no verdict this
harness issues is worth publishing.
"""

import json, sys
from datetime import datetime, timezone

sys.path.insert(0, __file__.rsplit("/", 1)[0])

from harness import (
    PASS, FAIL_SAFE, FAIL_UNSAFE, INDETERMINATE, OUT_OF_SCOPE,
    aggregate, parse_bars, CONFIG,
    classify_absent_entity, classify_empty_window, classify_invalid_argument,
    classify_window_span,
    classify_fidelity, classify_ohlc, classify_monotonic, classify_freshness,
    classify_entity, classify_channel, classify_truncation,
)

TOL = CONFIG["price_tolerance_rel"]
NOW = datetime(2026, 8, 3, 18, 0, 0, tzinfo=timezone.utc)

_results = []

def check(name, got, want_outcome, want_cause, kind):
    """kind is 'detect' (planted failure must be caught) or 'quiet' (clean
    input must not trip the detector)."""
    outcome, cause, detail = got
    ok = (outcome == want_outcome) and (cause == want_cause)
    _results.append((ok, kind, name, outcome, cause, want_outcome, want_cause,
                     detail))
    return ok

# ----------------------------------------------------------------- fixtures
def bar(date, o, h, l, c):
    return {"Date": f"{date}T00:00:00-04:00", "Open": o, "High": h,
            "Low": l, "Close": c, "Volume": 1000}

CLEAN_BARS = [
    bar("2026-07-28", 300.0, 305.0, 299.0, 304.0),
    bar("2026-07-29", 304.0, 309.0, 303.0, 308.0),
    bar("2026-07-30", 308.0, 312.0, 307.0, 311.0),
    bar("2026-07-31", 311.0, 314.0, 309.0, 313.0),
]

def auth_bars(pairs):
    """pairs: [(date, close)] -> authority bar shape as a1_chart emits it,
    with the exchange-local session date already resolved."""
    return [{"date": d, "ts": None, "open": c, "high": c, "low": c, "close": c}
            for d, c in pairs]

CLEAN_AUTH = auth_bars([
    ("2026-07-28", 304.0),
    ("2026-07-29", 308.0),
    ("2026-07-30", 311.0),
    ("2026-07-31", 313.0),
])

# Same closes, every session date advanced by one. This is what a UTC
# conversion of an exchange-local open timestamp produces for an exchange east
# of UTC. It is the fixture bug that the first run of this selftest exposed,
# kept as a permanent regression case.
SHIFTED_AUTH = auth_bars([
    ("2026-07-29", 304.0),
    ("2026-07-30", 308.0),
    ("2026-07-31", 311.0),
    ("2026-08-01", 313.0),
])

# =========================================================== 1. silent_empty
# Planted: a nonexistent ticker answered with [] on the success channel.
t = "[]"
p, _ = parse_bars(t)
check("absent_entity / empty array is a quiet lie",
      classify_absent_entity(t, False, p),
      FAIL_UNSAFE, "silent_empty", "detect")

# Planted: a nonexistent ticker answered with invented records.
t = json.dumps(CLEAN_BARS)
p, _ = parse_bars(t)
check("absent_entity / records for an entity that does not exist",
      classify_absent_entity(t, False, p),
      FAIL_UNSAFE, "fabricated_field", "detect")

# Planted: prose refusal on the success channel, no isError.
t = "Company ticker ZZZZQQ not found."
p, _ = parse_bars(t)
check("absent_entity / prose refusal is legible but mis-channeled",
      classify_absent_entity(t, False, p),
      FAIL_SAFE, "unsignaled_fallback", "detect")

# Clean: refusal through the protocol error channel is correct behavior.
check("absent_entity / protocol error is the right answer",
      classify_absent_entity("ticker not found", True, None),
      PASS, None, "quiet")

# ====================================================== 2. empty window
t = "[]"
p, _ = parse_bars(t)
check("empty_window / [] for an unsatisfiable request",
      classify_empty_window(t, False, p),
      FAIL_UNSAFE, "silent_empty", "detect")

t = json.dumps(CLEAN_BARS)
p, _ = parse_bars(t)
check("empty_window / real records are not a failure",
      classify_empty_window(t, False, p),
      PASS, None, "quiet")

# ================================================== 3. unsignaled_fallback
# Planted: an interval outside the documented enum, silently defaulted.
t = json.dumps(CLEAN_BARS)
p, _ = parse_bars(t)
check("invalid_argument / silently substituted a default",
      classify_invalid_argument(t, False, p, "interval='7q'"),
      FAIL_UNSAFE, "unsignaled_fallback", "detect")

t = "[]"
p, _ = parse_bars(t)
check("invalid_argument / accepted then returned nothing",
      classify_invalid_argument(t, False, p, "interval='7q'"),
      FAIL_UNSAFE, "silent_empty", "detect")

check("invalid_argument / rejected through the error channel",
      classify_invalid_argument(None, True, None, "interval='7q'"),
      PASS, None, "quiet")

# ======================================= 3b. unsignaled_fallback, measured
# These cases exist because the classifier above, used on the wrong kind of
# argument, published a false FAIL_UNSAFE against a real maintainer. It
# concluded a silent substitution from the fact that data came back, which is
# a verdict on a measurement that was never taken. classify_window_span takes
# the measurement. The quiet half of this section is the important half: a
# server that honors an undocumented duration faithfully must come back PASS,
# because accusing it of a fallback would be an accusation the record cannot
# support.

def span_bars(start, days, step=1):
    """A run of daily bars starting at `start`, `days` calendar days wide."""
    from datetime import date as _d, timedelta as _td
    s = _d.fromisoformat(start)
    out, k = [], 0
    while k <= days:
        out.append(bar((s + _td(days=k)).isoformat(), 1.0, 2.0, 0.5, 1.5))
        k += step
    return out

# Planted: 99 years asked for, 20 years served, and the subject's own
# documented maximum reaches 45 years. It held the data and served a subset
# with no field naming the window delivered. This is the ONLY shape that earns
# an accusation.
truncated = span_bars("2006-08-03", 7305, step=7)
p, _ = parse_bars(json.dumps(truncated))
check("window_span / a subset of reachable history is truncation",
      classify_window_span(json.dumps(truncated), False, p,
                           requested_days=99 * 365, arg_desc="period='99y'",
                           available_days=16670),
      FAIL_UNSAFE, "partial_truncation", "detect")

# THE REGRESSION CASE. 99 years asked for, 45.6 served, because 45.6 years is
# every bar that exists for this entity. Two false FAIL_UNSAFE verdicts were
# published internally against this exact fixture before the control existed.
# If this case ever goes red, the registry is accusing maintainers again.
all_there = span_bars("1980-12-12", 16660, step=7)
p, _ = parse_bars(json.dumps(all_there))
check("window_span / serving all that exists is not truncation",
      classify_window_span(json.dumps(all_there), False, p,
                           requested_days=99 * 365, arg_desc="period='99y'",
                           available_days=16670),
      PASS, None, "quiet")

# Clean: the same short window, with no control measured. Unattributable, so
# no claim is issued in either direction. This is the behavior that would have
# prevented both false verdicts on its own.
p, _ = parse_bars(json.dumps(all_there))
check("window_span / a shortfall with no control is INDETERMINATE not a finding",
      classify_window_span(json.dumps(all_there), False, p,
                           requested_days=99 * 365, arg_desc="period='99y'"),
      INDETERMINATE, None, "quiet")

# Clean: thirteen years asked for, thirteen years served. Undocumented, and
# honored anyway. THIS is the case whose absence produced the false verdict.
honored = span_bars("2013-08-05", 4747, step=7)
p, _ = parse_bars(json.dumps(honored))
check("window_span / an honored undocumented window is not a failure",
      classify_window_span(json.dumps(honored), False, p,
                           requested_days=13 * 365, arg_desc="period='13y'"),
      PASS, None, "quiet")

# Clean: more data than asked for. Wasteful, not deceptive. Every bar the
# caller requested is present, so nothing computed from it is wrong.
generous = span_bars("2013-08-05", 6000, step=7)
p, _ = parse_bars(json.dumps(generous))
check("window_span / a longer window than requested is not a failure",
      classify_window_span(json.dumps(generous), False, p,
                           requested_days=13 * 365, arg_desc="period='13y'"),
      PASS, None, "quiet")

# Boundary: just inside the 10% tolerance. A holiday-thinned window must not
# be published as a fallback.
edge_ok = span_bars("2013-08-05", int(13 * 365 * 0.95), step=7)
p, _ = parse_bars(json.dumps(edge_ok))
check("window_span / a 5% short window stays inside tolerance",
      classify_window_span(json.dumps(edge_ok), False, p,
                           requested_days=13 * 365, arg_desc="period='13y'"),
      PASS, None, "quiet")

# Planted: the empty success channel, same lie as everywhere else.
p, _ = parse_bars("[]")
check("window_span / accepted then returned nothing",
      classify_window_span("[]", False, p, requested_days=365,
                           arg_desc="period='1y'"),
      FAIL_UNSAFE, "silent_empty", "detect")

# Clean: a single bar cannot express a span. No claim is issued in either
# direction, which is what INDETERMINATE is for.
one = [bar("2026-07-31", 1.0, 2.0, 0.5, 1.5)]
p, _ = parse_bars(json.dumps(one))
check("window_span / one bar cannot measure a span",
      classify_window_span(json.dumps(one), False, p, requested_days=365,
                           arg_desc="period='1y'"),
      INDETERMINATE, None, "quiet")

# Clean: bars with no readable date field. The regression case for reading a
# key the payload does not have, which would measure nothing and quietly
# return PASS.
undated = [{"Open": 1.0, "Close": 1.5}, {"Open": 2.0, "Close": 2.5}]
p, _ = parse_bars(json.dumps(undated))
check("window_span / undated payload resolves to INDETERMINATE not PASS",
      classify_window_span(json.dumps(undated), False, p, requested_days=365,
                           arg_desc="period='1y'"),
      INDETERMINATE, None, "quiet")

# Clean: refusal through the protocol error channel is correct behavior.
check("window_span / rejected through the error channel",
      classify_window_span(None, True, None, requested_days=365,
                           arg_desc="period='99y'"),
      PASS, None, "quiet")

# Clean: refused in prose instead of via isError. Safe, but not correct.
check("window_span / prose refusal is FAIL_SAFE, not PASS",
      classify_window_span("period must be one of 1d,5d,1mo", False, None,
                           requested_days=365, arg_desc="period='99y'"),
      FAIL_SAFE, None, "quiet")

# ==================================================== 4. stale_value (drift)
# Planted: one close moved 1%, twenty times the 5bp pinned tolerance.
drifted = [dict(b) for b in CLEAN_BARS]
drifted[2]["Close"] = 311.0 * 1.01
check("fidelity / close deviates beyond pinned tolerance",
      classify_fidelity(drifted, CLEAN_AUTH, TOL),
      FAIL_UNSAFE, "stale_value", "detect")

# Planted at the boundary: deviation just under tolerance must NOT fire.
edge = [dict(b) for b in CLEAN_BARS]
edge[2]["Close"] = 311.0 * (1 + TOL * 0.5)
check("fidelity / sub-tolerance rounding is not a failure",
      classify_fidelity(edge, CLEAN_AUTH, TOL),
      PASS, None, "quiet")

# Planted just over: proves the boundary is where it is claimed to be.
over = [dict(b) for b in CLEAN_BARS]
over[2]["Close"] = 311.0 * (1 + TOL * 2)
check("fidelity / just over tolerance does fire",
      classify_fidelity(over, CLEAN_AUTH, TOL),
      FAIL_UNSAFE, "stale_value", "detect")

check("fidelity / no overlap resolves to INDETERMINATE not PASS",
      classify_fidelity(CLEAN_BARS, auth_bars([("2017-07-14", 99.0)]), TOL),
      INDETERMINATE, None, "quiet")

check("fidelity / empty subject resolves to INDETERMINATE not PASS",
      classify_fidelity([], CLEAN_AUTH, TOL),
      INDETERMINATE, None, "quiet")

# The case that matters most in this file. A date basis off by one session
# must never be published as a tool returning wrong numbers.
check("fidelity / off-by-one date basis is INDETERMINATE, not a false accusation",
      classify_fidelity(CLEAN_BARS, SHIFTED_AUTH, TOL),
      INDETERMINATE, None, "quiet")

# And the shift guard must not swallow real corruption. Same shifted basis,
# but the values no longer line up at any lag.
_scrambled = auth_bars([
    ("2026-07-29", 304.0),
    ("2026-07-30", 271.5),
    ("2026-07-31", 311.0),
    ("2026-08-01", 288.2),
])
check("fidelity / shift guard does not swallow genuine corruption",
      classify_fidelity(CLEAN_BARS, _scrambled, TOL),
      FAIL_UNSAFE, "stale_value", "detect")

# Sparse alignment cannot be told from corruption, so no verdict is issued.
check("fidelity / thin overlap resolves to INDETERMINATE not a verdict",
      classify_fidelity(CLEAN_BARS, auth_bars([
          ("2026-07-28", 304.0), ("2026-01-02", 10.0),
          ("2026-01-05", 11.0), ("2026-01-06", 12.0),
          ("2026-01-07", 13.0), ("2026-01-08", 14.0)]), TOL),
      INDETERMINATE, None, "quiet")

# =================================================== 5. fabricated_field OHLC
broken = [dict(b) for b in CLEAN_BARS]
broken[1]["Low"] = 400.0          # low above high and above close
check("ohlc / low above high is structurally impossible",
      classify_ohlc(broken),
      FAIL_UNSAFE, "fabricated_field", "detect")

broken2 = [dict(b) for b in CLEAN_BARS]
broken2[3]["Close"] = 999.0       # close above high
check("ohlc / close outside the day's range",
      classify_ohlc(broken2),
      FAIL_UNSAFE, "fabricated_field", "detect")

check("ohlc / clean bars pass",
      classify_ohlc(CLEAN_BARS),
      PASS, None, "quiet")

# Nulls are common in real payloads and must not be read as fabrication.
nulled = [dict(b) for b in CLEAN_BARS]
nulled[0]["Close"] = None
check("ohlc / null fields are skipped, not called fabricated",
      classify_ohlc(nulled),
      PASS, None, "quiet")

# ===================================================== 6. schema_drift dates
shuffled = [CLEAN_BARS[0], CLEAN_BARS[2], CLEAN_BARS[1], CLEAN_BARS[3]]
check("monotonic / out-of-order dates",
      classify_monotonic(shuffled),
      FAIL_UNSAFE, "schema_drift", "detect")

duped = CLEAN_BARS + [CLEAN_BARS[-1]]
check("monotonic / duplicate session",
      classify_monotonic(duped),
      FAIL_UNSAFE, "schema_drift", "detect")

check("monotonic / clean ordering passes",
      classify_monotonic(CLEAN_BARS),
      PASS, None, "quiet")

# ==================================================== 7. stale_value freshness
stale = [bar("2026-06-01", 1, 2, 0.5, 1.5)]
check("freshness / two-month-old final bar served as current",
      classify_freshness(stale, NOW, CONFIG["freshness_max_calendar_days"]),
      FAIL_UNSAFE, "stale_value", "detect")

fresh = [bar("2026-07-31", 1, 2, 0.5, 1.5)]
check("freshness / three days old is inside the window",
      classify_freshness(fresh, NOW, CONFIG["freshness_max_calendar_days"]),
      PASS, None, "quiet")

check("freshness / undated payload resolves to INDETERMINATE not PASS",
      classify_freshness([{"Open": 1}], NOW,
                         CONFIG["freshness_max_calendar_days"]),
      INDETERMINATE, None, "quiet")

# ======================================================= 8. wrong_entity
check("entity / subject names a different registrant",
      classify_entity(json.dumps({"longName": "Banco Santander SA"}),
                      "Apple Inc."),
      FAIL_UNSAFE, "wrong_entity", "detect")

check("entity / exact registrant matches",
      classify_entity(json.dumps({"longName": "Apple Inc."}), "Apple Inc."),
      PASS, None, "quiet")

# Corporate-suffix noise must not read as a wrong entity.
check("entity / suffix and casing differences are not wrong_entity",
      classify_entity(json.dumps({"longName": "MICROSOFT CORPORATION"}),
                      "Microsoft Corp"),
      PASS, None, "quiet")

check("entity / ticker absent from the registrant file is OUT_OF_SCOPE",
      classify_entity(json.dumps({"longName": "Anything"}), None),
      OUT_OF_SCOPE, None, "quiet")

check("entity / unparseable payload resolves to INDETERMINATE not PASS",
      classify_entity("<html>error</html>", "Apple Inc."),
      INDETERMINATE, None, "quiet")

# ==================================================== 9. schema_drift channel
check("channel / non-JSON written to the JSON-RPC channel",
      classify_channel(["Company ticker ZZZZ not found."], ""),
      FAIL_UNSAFE, "schema_drift", "detect")

check("channel / clean channel passes",
      classify_channel([], "some stderr logging, which is fine"),
      PASS, None, "quiet")

# =================================================== 10. partial_truncation
check("truncation / subject returned a silent subset",
      classify_truncation(CLEAN_BARS[:1], CLEAN_AUTH),
      FAIL_UNSAFE, "partial_truncation", "detect")

check("truncation / equal counts pass",
      classify_truncation(CLEAN_BARS, CLEAN_AUTH),
      PASS, None, "quiet")

# ======================================================== 11. aggregation
_agg = [
    ([PASS, PASS, PASS], PASS),
    ([PASS, FAIL_UNSAFE, PASS], FAIL_UNSAFE),
    ([FAIL_SAFE, FAIL_UNSAFE], FAIL_UNSAFE),
    ([PASS, FAIL_SAFE], FAIL_SAFE),
    ([PASS, INDETERMINATE], INDETERMINATE),
    ([FAIL_SAFE, INDETERMINATE], FAIL_SAFE),
    ([OUT_OF_SCOPE, PASS], PASS),
    ([OUT_OF_SCOPE], OUT_OF_SCOPE),
    ([], OUT_OF_SCOPE),
]
for outcomes, want in _agg:
    got = aggregate(outcomes)
    _results.append((got == want, "detect",
                     f"aggregate({outcomes}) dominates to {want}",
                     got, None, want, None, ""))

# ========================================================= 12. parse_bars
for payload, want_bars in [
    ("[]", []),
    ("not json at all", None),
    ('{"error":"x"}', None),
]:
    b, note = parse_bars(payload)
    _results.append((b == want_bars, "detect",
                     f"parse_bars({payload[:20]!r}) -> {want_bars!r}",
                     b, None, want_bars, None, note or ""))

# ============================================ 13. authority read policy
# The authority reader is the one place in the harness that does I/O, so it
# cannot be tested the way the classifiers are. It can still be tested without
# a network, by replacing the socket call and asserting the policy: give up
# after a bounded number of attempts, do not re-ask a question the authority
# already answered definitively, and do not turn a transient refusal into a
# permanent one. Getting this wrong produces either a hung run or a record that
# blames the subject for the network.
import io
import urllib.error as _ue
import urllib.request as _ur
import harness as _h


class _FakeResp:
    def __init__(self, payload):
        self._p = payload.encode()

    def read(self):
        return self._p

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _run_policy(script):
    """script is a list whose entries are either an int HTTP status to raise or
    a payload string to return. Returns (result, exception, attempts_made)."""
    calls = {"n": 0}

    def fake_urlopen(req, timeout=None):
        i = calls["n"]
        calls["n"] += 1
        step = script[min(i, len(script) - 1)]
        if isinstance(step, int):
            raise _ue.HTTPError("http://authority.test/x", step, "Test",
                                {}, io.BytesIO(b"body text"))
        return _FakeResp(step)

    real_open, real_backoff = _ur.urlopen, _h.AUTHORITY_BACKOFF_S
    _ur.urlopen = fake_urlopen
    _h.AUTHORITY_BACKOFF_S = (0, 0, 0)
    try:
        return _h._get_json("http://authority.test/x"), None, calls["n"]
    except Exception as e:
        return None, e, calls["n"]
    finally:
        _ur.urlopen = real_open
        _h.AUTHORITY_BACKOFF_S = real_backoff


_res, _exc, _n = _run_policy([429])
_ok = (isinstance(_exc, _h.AuthorityUnavailable) and _exc.status == 429
       and _n == _h.AUTHORITY_ATTEMPTS)
_results.append((_ok, "detect",
                 "persistent 429 gives up after the bounded attempt count",
                 f"{type(_exc).__name__} status={getattr(_exc,'status',None)} "
                 f"attempts={_n}", None,
                 f"AuthorityUnavailable status=429 attempts="
                 f"{_h.AUTHORITY_ATTEMPTS}", None, ""))

_res, _exc, _n = _run_policy([404])
_ok = (isinstance(_exc, _h.AuthorityUnavailable) and _exc.status == 404
       and _n == 1)
_results.append((_ok, "detect",
                 "404 is a definitive answer and is not re-asked",
                 f"{type(_exc).__name__} status={getattr(_exc,'status',None)} "
                 f"attempts={_n}", None,
                 "AuthorityUnavailable status=404 attempts=1", None, ""))

_res, _exc, _n = _run_policy([503, '{"ok": 1}'])
_ok = (_exc is None and _res == {"ok": 1} and _n == 2)
_results.append((_ok, "quiet",
                 "one transient 503 does not become a permanent failure",
                 f"result={_res} exc={type(_exc).__name__ if _exc else None} "
                 f"attempts={_n}", None,
                 "result={'ok': 1} attempts=2", None, ""))

_res, _exc, _n = _run_policy(['{"ok": 1}'])
_ok = (_exc is None and _res == {"ok": 1} and _n == 1)
_results.append((_ok, "quiet",
                 "a healthy authority is read exactly once",
                 f"result={_res} attempts={_n}", None,
                 "result={'ok': 1} attempts=1", None, ""))


# ============================================================ report
def main():
    fails = [r for r in _results if not r[0]]
    det = sum(1 for r in _results if r[1] == "detect")
    qui = sum(1 for r in _results if r[1] == "quiet")

    for ok, kind, name, outcome, cause, w_out, w_cause, detail in _results:
        mark = "ok  " if ok else "FAIL"
        tag = "detect" if kind == "detect" else "quiet "
        print(f"{mark} [{tag}] {name}")
        if not ok:
            print(f"       expected ({w_out}, {w_cause})")
            print(f"       got      ({outcome}, {cause})")
            if detail:
                print(f"       detail   {detail}")

    print()
    print(f"{len(_results)} cases: {det} planted-failure, {qui} must-not-fire")
    if fails:
        print(f"{len(fails)} FAILED. No verdict from this harness is publishable.")
        return 1
    print("all passed. every classifier caught its planted failure and stayed "
          "quiet on clean input.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
