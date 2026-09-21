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

No network. The classifiers are pure, which is the entire reason this file
can exist, and nothing above section 10d starts a process. The two
repository-level sections do: hold.py's checks are about what git has,
and a fixture that cannot hold a commit cannot test them. Those build
throwaway repositories in temp directories and delete them.

Exit code 0 only if every case passes. Anything else means no verdict this
harness issues is worth publishing.
"""

import json, os, subprocess, sys
from datetime import datetime, timezone

# Git exports repository-local variables to hooks. cwd alone cannot isolate
# the temporary fixture repositories while GIT_DIR, GIT_INDEX_FILE, etc.
# still point at the caller. Previously a worktree pre-push run failed 13
# cases and fixture commits changed the caller's HEAD/index and core.bare.
# Clear Git's own list in this test process only, before any fixture imports
# or commands. The parent hook's export checks retain their original context.
for _git_env_name in subprocess.check_output(
        ["git", "rev-parse", "--local-env-vars"], text=True).splitlines():
    os.environ.pop(_git_env_name, None)

sys.path.insert(0, __file__.rsplit("/", 1)[0])

from harness import (
    PASS, FAIL_SAFE, FAIL_UNSAFE, INDETERMINATE, OUT_OF_SCOPE,
    aggregate, parse_bars, CONFIG, next_in_sequence,
    a1_chart, AuthorityUnavailable,
    classify_absent_entity, classify_empty_window, classify_invalid_argument,
    classify_padded_argument,
    classify_window_span,
    classify_fidelity, classify_range_fidelity, classify_ohlc,
    classify_monotonic, classify_freshness,
    classify_entity, classify_channel, classify_truncation,
)

TOL = CONFIG["price_tolerance_rel"]
NOW = datetime(2026, 8, 3, 18, 0, 0, tzinfo=timezone.utc)

_results = []

def safe(fn, *a, **kw):
    """Call a classifier and turn a raised exception into a reportable result.

    A classifier that raises used to take this whole file down with it, so the
    suite reported a traceback instead of a red case and every check after the
    crash went unrun. That is the same shape as the defects being tested for: a
    failure that destroys the report rather than appearing in it. Two
    classify_window_span inputs raised, which is how this was noticed.
    """
    try:
        return fn(*a, **kw)
    except Exception as e:
        return ("RAISED:%s" % type(e).__name__, str(e)[:80], "classifier raised")


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

# The prose alternation includes the bare token `error` and was matched against
# the RAW payload text, so it matched a JSON field NAME. These two payloads are
# the same fabrication -- an invented price for a ticker that does not exist --
# and the second one differs only by a null field that a struct serialized
# without omitempty emits for free. It graded FAIL_SAFE "said 'not found' in
# prose" while the first graded FAIL_UNSAFE. A missing struct tag downgraded
# the tier of a fabrication.
_ae_plain = '[{"Date": "2026-09-12", "Close": 1.0}]'
_ae_null = '[{"Date": "2026-09-12", "Close": 1.0, "error": null}]'
_ae_empty = '[{"Date": "2026-09-12", "Close": 1.0, "error": ""}]'

check("absent_entity / a null error field is not an utterance",
      classify_absent_entity(_ae_null, False, json.loads(_ae_null)),
      FAIL_UNSAFE, "fabricated_field", "detect")

check("absent_entity / an empty error field is not an utterance either",
      classify_absent_entity(_ae_empty, False, json.loads(_ae_empty)),
      FAIL_UNSAFE, "fabricated_field", "detect")

_results.append((classify_absent_entity(_ae_null, False,
                                        json.loads(_ae_null))[:2]
                 == classify_absent_entity(_ae_plain, False,
                                           json.loads(_ae_plain))[:2],
                 "detect",
                 "absent_entity / an omitempty tag does not change the tier",
                 classify_absent_entity(_ae_null, False, json.loads(_ae_null))[1],
                 None,
                 classify_absent_entity(_ae_plain, False, json.loads(_ae_plain))[1],
                 None,
                 "the same fabrication graded the same with and without the field"))

# must not fire. The prose check runs before the parsed-list check precisely so
# that a subject which says in words that the entity is absent is graded on
# what it said, not counted as having invented a record. All three of these
# refusals have to survive the narrowing.
_ae_ref = '[{"error": "No data found for ZZZZQQ, symbol may be delisted"}]'
check("absent_entity / a refusal carried as a string value is still FAIL_SAFE",
      classify_absent_entity(_ae_ref, False, json.loads(_ae_ref)),
      FAIL_SAFE, "unsignaled_fallback", "quiet")

_ae_str = '["No data found for ZZZZQQ"]'
check("absent_entity / a refusal as a bare string element is still FAIL_SAFE",
      classify_absent_entity(_ae_str, False, json.loads(_ae_str)),
      FAIL_SAFE, "unsignaled_fallback", "quiet")

_ae_obj = '{"error": "ticker not found"}'
check("absent_entity / a refusal that is not a record array is still FAIL_SAFE",
      classify_absent_entity(_ae_obj, False, parse_bars(_ae_obj)[0]),
      FAIL_SAFE, "unsignaled_fallback", "quiet")

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

# ============================================ 2b. the authority reader itself
# a1_chart had no coverage at all. It is the one function whose failures are
# claims about a third party's service rather than about a subject: run.py
# catches what escapes here and writes reachable: false with a Python type
# name as the reason. Measured before these were written, five ordinary
# response shapes did exactly that. A JSON null is what an upstream sends when
# it has nothing to say about a field, which is most fields, most of the time.

def _chart(result, error=None):
    return {"chart": {"result": result, "error": error}}

_GOODQ = {"open": [1.0], "high": [2.0], "low": [0.5], "close": [1.5]}

def _a1(payload):
    """a1_chart against a stubbed fetch. Returns the outcome as a token."""
    import harness as _h
    keep = _h._get_json
    _h._get_json = lambda url, **kw: payload
    try:
        r = _h.a1_chart("AAPL", "1d", "5d")
        return ("bars", len(r["bars"]), r.get("tz_basis"))
    except AuthorityUnavailable as e:
        return ("refused", None, str(e)[:90])
    except Exception as e:
        return ("RAW:" + type(e).__name__, None, str(e)[:90])
    finally:
        _h._get_json = keep

check("a1_chart / a result that is not a list is refused, not raised",
      _a1(_chart({"a": 1})), "refused", None, "detect")

check("a1_chart / a result entry that is not an object is refused",
      _a1(_chart(["x"])), "refused", None, "detect")

check("a1_chart / a timestamp array that is null is refused",
      _a1(_chart([{"meta": {"symbol": "AAPL"}, "timestamp": None,
                   "indicators": {"quote": [{}]}}])),
      "refused", None, "detect")

# A scalar timestamp rather than a string, deliberately. A string is caught
# downstream by the finite-number check, which enumerates its characters and
# finds none are numbers, so a string does not isolate this guard: disabling
# the guard leaves a string still refused, by the next one. A bare int is not
# iterable at all, so without this guard it raises TypeError out of the
# function and run.py records the authority as unreachable.
check("a1_chart / a timestamp that is not iterable is refused, not raised",
      _a1(_chart([{"meta": {"symbol": "AAPL"}, "timestamp": 1757000000,
                   "indicators": {"quote": [_GOODQ]}}])),
      "refused", None, "detect")

check("a1_chart / a null inside the timestamp array is refused",
      _a1(_chart([{"meta": {"symbol": "AAPL"}, "timestamp": [None],
                   "indicators": {"quote": [_GOODQ]}}])),
      "refused", None, "detect")

check("a1_chart / a quote block that is a list is refused",
      _a1(_chart([{"meta": {"symbol": "AAPL"}, "timestamp": [1757000000],
                   "indicators": {"quote": [[]]}}])),
      "refused", None, "detect")

# must not fire: the reader still reads an ordinary answer, and still tolerates
# a missing meta, because meta carries the symbol and timezone and its absence
# is recorded in tz_basis rather than treated as a broken response.
check("a1_chart / an ordinary payload still yields bars",
      _a1(_chart([{"meta": {"symbol": "AAPL", "gmtoffset": -14400},
                   "timestamp": [1757000000],
                   "indicators": {"quote": [_GOODQ]}}])),
      "bars", 1, "quiet")

check("a1_chart / a null meta is tolerated, not refused",
      _a1(_chart([{"meta": None, "timestamp": [1757000000],
                   "indicators": {"quote": [_GOODQ]}}])),
      "bars", 1, "quiet")

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

# Non-finite inputs. Both guards below already existed and both admitted nan,
# because nan is a float and every comparison against it is False.
#
# requested_days=nan was the serious one. It cleared "requested_days <= 0",
# ratio became nan, "nan >= 1.0 - tol" was False so the short path ran,
# min(nan, available) returned nan, "served >= nan" was False, and the
# classifier returned FAIL_UNSAFE partial_truncation about a subject that had
# served the window in full. Every comparison failed open toward an
# accusation, which is the single direction this harness must not fail in.
_full = [{"Date": d, "Close": 1.0} for d in ("2026-01-01", "2026-12-31")]
_short = [{"Date": d, "Close": 1.0} for d in ("2026-01-01", "2026-03-01")]

check("window_span / a nan request does not become an accusation",
      classify_window_span("x", False, _full, requested_days=float("nan"),
                           arg_desc="period=?", available_days=365),
      INDETERMINATE, None, "detect")

check("window_span / an infinite request is not a window either",
      classify_window_span("x", False, _full, requested_days=float("inf"),
                           arg_desc="period=?", available_days=365),
      INDETERMINATE, None, "detect")

# available_days is the entire basis for attributing a shortfall. Zero is not
# a measurement of reachable history, it is the absence of one, and it used to
# produce a vacuous pass: owed became min(requested, 0) = 0, "served >= 0" held
# for every payload, and the evidence read "the request was honored to the
# limit of what the subject could reach (0 days available, 0 owed)" about a
# subject that had just served 364 days.
check("window_span / zero reachable history cannot explain a shortfall",
      classify_window_span("x", False, _short, requested_days=365,
                           arg_desc="period=max", available_days=0),
      INDETERMINATE, None, "detect")

check("window_span / negative reachable history cannot explain one either",
      classify_window_span("x", False, _short, requested_days=365,
                           arg_desc="period=max", available_days=-10),
      INDETERMINATE, None, "detect")

check("window_span / a nan availability cannot explain one either",
      classify_window_span("x", False, _short, requested_days=365,
                           arg_desc="period=max", available_days=float("nan")),
      INDETERMINATE, None, "detect")

# must not fire: the probe still has to reach all three real verdicts, or the
# guards above have turned it into an abstention machine.
check("window_span / a genuine withholding is still caught",
      classify_window_span("x", False, _short, requested_days=365,
                           arg_desc="period=max", available_days=365),
      FAIL_UNSAFE, "partial_truncation", "quiet")

check("window_span / a real availability limit still explains a shortfall",
      classify_window_span("x", False, _short, requested_days=365,
                           arg_desc="period=max", available_days=59),
      PASS, None, "quiet")

check("window_span / a fully served window still passes",
      classify_window_span("x", False, _full, requested_days=365,
                           arg_desc="period=max", available_days=365),
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

# ================= 4a-ii. range fidelity: Open, High and Low, not just Close
# classify_fidelity above never looks past Close. A subject that reports the
# authority's Close correctly but fabricates a plausible Open, High or Low
# around it passed every check that existed: classify_ohlc only checks a
# bar's own four values against each other, and fidelity never checked range
# against the source. classify_range_fidelity is a separate function, not a
# change to classify_fidelity, exactly because every fidelity fixture above
# uses auth_bars(), which sets Open=High=Low=Close for every session, and
# comparing that flat authority against CLEAN_BARS' real OHLC would fail on
# every one of them for a reason that has nothing to do with what those
# cases test. This authority fixture carries real, distinct OHLC instead.

RANGE_AUTH = [
    {"date": "2026-07-28", "open": 300.0, "high": 305.0, "low": 299.0,
     "close": 304.0},
    {"date": "2026-07-29", "open": 304.0, "high": 309.0, "low": 303.0,
     "close": 308.0},
    {"date": "2026-07-30", "open": 308.0, "high": 312.0, "low": 307.0,
     "close": 311.0},
    {"date": "2026-07-31", "open": 311.0, "high": 314.0, "low": 309.0,
     "close": 313.0},
]

check("range fidelity / a faithful subject's real OHLC passes",
      classify_range_fidelity(CLEAN_BARS, RANGE_AUTH, TOL),
      PASS, None, "quiet")

_fab_high = [dict(b) for b in CLEAN_BARS]
_fab_high[1] = dict(_fab_high[1], High=_fab_high[1]["High"] * 1.05)
check("range fidelity / a fabricated High around a correct Close is caught",
      classify_range_fidelity(_fab_high, RANGE_AUTH, TOL),
      FAIL_UNSAFE, "stale_value", "detect")

_fab_low = [dict(b) for b in CLEAN_BARS]
_fab_low[2] = dict(_fab_low[2], Low=_fab_low[2]["Low"] * 0.9)
check("range fidelity / a fabricated Low is caught the same way",
      classify_range_fidelity(_fab_low, RANGE_AUTH, TOL),
      FAIL_UNSAFE, "stale_value", "detect")

_range_edge = [dict(b) for b in CLEAN_BARS]
_range_edge[0] = dict(_range_edge[0],
                      Open=_range_edge[0]["Open"] * (1 + TOL * 0.5))
check("range fidelity / sub-tolerance drift on Open is not a failure",
      classify_range_fidelity(_range_edge, RANGE_AUTH, TOL),
      PASS, None, "quiet")

check("range fidelity / a subject with no Open/High/Low is not accused",
      classify_range_fidelity(
          [{"Date": b["Date"][:10], "Close": b["Close"]} for b in CLEAN_BARS],
          RANGE_AUTH, TOL),
      INDETERMINATE, None, "quiet")

_close_only_auth = [{"date": "2026-07-28", "close": 304.0},
                    {"date": "2026-07-29", "close": 308.0},
                    {"date": "2026-07-30", "close": 311.0},
                    {"date": "2026-07-31", "close": 313.0}]
check("range fidelity / an authority with no Open/High/Low is not treated "
      "as agreement",
      classify_range_fidelity(CLEAN_BARS, _close_only_auth, TOL),
      INDETERMINATE, None, "quiet")

check("range fidelity / CLEAN_AUTH's flat Open=High=Low=Close is real range "
      "data, not absent data, and a mismatch against it is caught",
      classify_range_fidelity(CLEAN_BARS, CLEAN_AUTH, TOL),
      FAIL_UNSAFE, "stale_value", "detect")

check("range fidelity / empty subject resolves to INDETERMINATE not PASS",
      classify_range_fidelity([], RANGE_AUTH, TOL),
      INDETERMINATE, None, "quiet")

check("range fidelity / no overlap resolves to INDETERMINATE not PASS",
      classify_range_fidelity(CLEAN_BARS, [
          {"date": "2017-07-14", "open": 99.0, "high": 99.5, "low": 98.5,
           "close": 99.0}], TOL),
      INDETERMINATE, None, "quiet")

_zero_range_auth = [dict(b, open=0.0, high=0.0, low=0.0) for b in RANGE_AUTH]
check("range fidelity / an authority range of zero is undefined, not a pass",
      classify_range_fidelity(CLEAN_BARS, _zero_range_auth, TOL),
      INDETERMINATE, None, "quiet")

# ============================ 4b. a padded argument is not an unhonorable one
# P11 sent period='1mo ' and judged the answer with classify_invalid_argument,
# whose contract is that the presence of data is itself the evidence. That
# contract holds only when no reading of the argument makes data a correct
# answer. A trailing space has an obvious reading, and a tool that strips it
# and serves one month is CORRECT, so the probe returned FAIL_UNSAFE
# unsignaled_fallback, "which has no valid interpretation", against
# essentially every well-behaved subject.
#
# The probe's own comment always described the honest test: if the padded and
# unpadded forms disagree, the disagreement should be audible. It never
# fetched the unpadded form. Now it does, and the finding rests on an observed
# difference rather than on the mere existence of a response.

def _pbars(n, start=1):
    return [{"Date": "2026-09-%02d" % (i + start), "Open": 1, "High": 2,
             "Low": 0.5, "Close": 1.5} for i in range(n)]
_PJ = lambda b: json.dumps(b)
_ARG = "period='1mo ' (trailing space)"

# must not fire: every one of these is a correct tool.
check("padded / stripping the space and serving the same window is correct",
      classify_padded_argument(_PJ(_pbars(23)), False, _pbars(23),
                               _PJ(_pbars(23)), False, _pbars(23), _ARG),
      PASS, None, "quiet")

check("padded / refusing a padded argument outright is also correct",
      classify_padded_argument(None, True, None,
                               _PJ(_pbars(23)), False, _pbars(23), _ARG),
      PASS, None, "quiet")

# detect: the two shapes that are actually a silent substitution.
check("padded / serving a different number of sessions is a substitution",
      classify_padded_argument(_PJ(_pbars(5)), False, _pbars(5),
                               _PJ(_pbars(23)), False, _pbars(23), _ARG),
      FAIL_UNSAFE, "unsignaled_fallback", "detect")

check("padded / serving a shifted window of the same size is one too",
      classify_padded_argument(_PJ(_pbars(23, 1)), False, _pbars(23, 1),
                               _PJ(_pbars(23, 2)), False, _pbars(23, 2), _ARG),
      FAIL_UNSAFE, "unsignaled_fallback", "detect")

# no control, no claim. Without the unpadded fetch there is nothing to
# compare against, and inferring a fallback from the response alone is the
# defect this section exists for.
check("padded / an unreadable control issues no claim in either direction",
      classify_padded_argument(_PJ(_pbars(23)), False, _pbars(23),
                               None, False, None, _ARG),
      INDETERMINATE, None, "quiet")

check("padded / a prose refusal is FAIL_SAFE, not a silent fallback",
      classify_padded_argument("invalid period", False, None,
                               _PJ(_pbars(23)), False, _pbars(23), _ARG),
      FAIL_SAFE, None, "quiet")


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

# A payload this probe cannot order used to return OUT_OF_SCOPE, which _ORDER
# ranks LAST, below PASS, so the branch could never move an aggregate verdict
# no matter what the subject sent. OUT_OF_SCOPE means the question does not
# apply to this subject; here the subject answered and the answer could not be
# read, which is INDETERMINATE. Empty input two lines up in the classifier
# already returned INDETERMINATE, so a payload of unreadable entries was graded
# SOFTER than no payload at all, and the two sibling probes reading the same
# bytes both said INDETERMINATE.
check("monotonic / entries that are not records are INDETERMINATE not OUT_OF_SCOPE",
      classify_monotonic([1, 2, 3, 4]),
      INDETERMINATE, None, "detect")

check("monotonic / a bar carrying no Date is not out of scope",
      classify_monotonic([{"Date": "2026-09-12"}, {"Close": 1.0}]),
      INDETERMINATE, None, "detect")

check("monotonic / one dated bar establishes no ordering",
      classify_monotonic([{"Date": "2026-09-12"}]),
      INDETERMINATE, None, "detect")

# The whole point of the tier change: this verdict has to be able to move a run.
_results.append((aggregate(["PASS", classify_monotonic([1, 2, 3, 4])[0],
                            "PASS"]) == INDETERMINATE, "detect",
                 "monotonic / an unreadable payload moves the aggregate off PASS",
                 aggregate(["PASS", classify_monotonic([1, 2, 3, 4])[0], "PASS"]),
                 None, INDETERMINATE, None,
                 "a verdict ranked below PASS is a verdict that cannot be heard"))

# must not fire: the three probes that read the same payload must not disagree
# about whether they could read it.
_results.append((classify_monotonic([1, 2, 3, 4])[0]
                 == classify_ohlc([1, 2, 3, 4])[0], "quiet",
                 "monotonic / agrees with classify_ohlc on the same unreadable payload",
                 classify_monotonic([1, 2, 3, 4])[0], None,
                 classify_ohlc([1, 2, 3, 4])[0], None,
                 "sibling probes reading the same bytes reached the same verdict"))

# ============================== 6b. nan and inf are not prices
# _numeric admitted both, because both are instances of float, and each broke
# a different comparison in a different direction.
#
# The fidelity case is the one worth stating plainly. Every comparison against
# nan is False, so `rel > worst` never fired and `worst` stayed 0.0. A payload
# whose every close was nan returned PASS with the evidence string "4
# overlapping sessions compared, worst deviation 0.00000% within tolerance".
# Nothing was compared. The sentence asserted the comparison the nan had just
# prevented, which is the same defect shape the register grades others for.

NAN, INF = float("nan"), float("inf")
_auth4 = [{"date": d, "close": 100.0} for d in
          ("2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04")]
def _sub4(closes):
    return [{"Date": d, "Close": c} for d, c in zip(
        ("2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"), closes)]
_TOL = CONFIG["price_tolerance_rel"]
_OV = CONFIG["fidelity_min_overlap_frac"]

check("fidelity / every close nan is not a clean comparison, it is no comparison",
      classify_fidelity(_sub4([NAN] * 4), _auth4, _TOL, _OV),
      INDETERMINATE, None, "detect")

check("fidelity / a single nan close is not silently dropped into a pass",
      classify_fidelity(_sub4([100.0, NAN, 100.0, 100.0]), _auth4, _TOL, _OV),
      INDETERMINATE, None, "detect")

check("fidelity / an infinite close is not a readable price",
      classify_fidelity(_sub4([100.0, INF, 100.0, 100.0]), _auth4, _TOL, _OV),
      INDETERMINATE, None, "detect")

# must not fire: the probe still has to catch a real deviation, and still has
# to pass a payload that genuinely matches. A guard that resolves everything
# to INDETERMINATE is not a guard, it is an abstention.
# The authority side of the same nan hole. _numeric was applied to the
# subject's closes and not to the authority's, so the fix left the third
# caller its own docstring names uncovered. json.loads accepts the bare token
# NaN, so it arrives from the wire intact, and the consequence is identical:
# nan == 0 is False so the session counts as compared, rel is nan, nan > worst
# is False, and the probe returns PASS reading "worst deviation 0.00000%
# within tolerance" while comparing against nothing.
_auth_nan = [{"date": d, "close": NAN} for d in
             ("2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04")]
check("fidelity / an authority column of nan is nothing to compare against",
      classify_fidelity(_sub4([100.0] * 4), _auth_nan, _TOL, _OV),
      INDETERMINATE, None, "detect")

_auth_inf = [{"date": d, "close": INF} for d in
             ("2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04")]
check("fidelity / an infinite authority close is not a readable price either",
      classify_fidelity(_sub4([100.0] * 4), _auth_inf, _TOL, _OV),
      INDETERMINATE, None, "detect")

check("fidelity / a real 50% deviation is still caught",
      classify_fidelity(_sub4([100.0, 150.0, 100.0, 100.0]), _auth4, _TOL, _OV),
      FAIL_UNSAFE, "stale_value", "quiet")

check("fidelity / a payload that matches the authority still passes",
      classify_fidelity(_sub4([100.0] * 4), _auth4, _TOL, _OV),
      PASS, None, "quiet")

def _q(o, h, l, c):
    return [{"Date": "2026-08-0%d" % (i + 1), "Open": o, "High": h,
             "Low": l, "Close": c} for i in range(1, 5)]

check("ohlc / an infinite high satisfies every inequality and is still unreadable",
      classify_ohlc(_q(100.0, INF, 99.0, 100.5)),
      INDETERMINATE, None, "detect")

check("ohlc / a nan quadruple is unreadable, not an inequality violation",
      classify_ohlc(_q(NAN, NAN, NAN, NAN)),
      INDETERMINATE, None, "detect")

check("ohlc / a clean quadruple still passes",
      classify_ohlc(_q(100.0, 101.0, 99.0, 100.5)),
      PASS, None, "quiet")

# ================== 6c. equal counts over nearly-different sessions
# The no-overlap case was already graded and the guard was binary, so a single
# shared date defeated it. A subject serving 100 sessions that share one day
# with the authority's 100 returned PASS reading "subject 100 sessions,
# authority 100". The docstring said equal counts are not the same window,
# and the code only enforced it when the windows were disjoint.

from datetime import date as _date, timedelta as _td2
def _span(start, n):
    d0 = _date.fromisoformat(start)
    return [{"Date": (d0 + _td2(days=i)).isoformat(), "Close": 100.0}
            for i in range(n)]
def _auth_span(start, n):
    """Authority-shaped bars, and the distinction is the whole point.

    a1_chart emits `date` and `ts`, not `Date`. The first version of these
    cases built both sides with _span, so the authority side carried the
    subject's key. _iso_dates only read `Date`, which meant `ad` was populated
    here and empty against every real authority payload, so the window
    comparison ran in this file and never in production. Equal counts over
    different windows passed live while these cases reported it caught.

    A fixture that does not have the shape the code meets is a test of a
    branch nothing reaches.
    """
    d0 = _date.fromisoformat(start)
    return [{"date": (d0 + _td2(days=i)).isoformat(), "ts": 0, "close": 100.0}
            for i in range(n)]

_AUTH100 = _auth_span("2026-05-01", 100)

check("truncation / one shared day out of a hundred is not a clean window",
      classify_truncation(_span("2026-01-22", 100), _AUTH100),
      INDETERMINATE, None, "detect")

check("truncation / a fifth of the window shared is still not a result",
      classify_truncation(_span("2026-02-10", 100), _AUTH100),
      INDETERMINATE, None, "detect")

# must not fire: above the pinned floor the windows are the same window, and a
# real truncation still has to be caught. A probe that resolves every
# comparison to INDETERMINATE has stopped answering the question.
check("truncation / a majority-shared window is judged, not abstained on",
      classify_truncation(_span("2026-03-13", 100), _AUTH100),
      PASS, None, "quiet")

check("truncation / a genuine short serve is still caught",
      classify_truncation(_span("2026-05-01", 30), _AUTH100),
      FAIL_UNSAFE, "partial_truncation", "quiet")

check("truncation / an identical window still passes",
      classify_truncation(_span("2026-05-01", 100), _AUTH100),
      PASS, None, "quiet")

# A count is not a window. parse_bars accepts any JSON list as the record
# array, so a subject can hand this function four integers, four nulls or four
# empty dicts and they arrive as four bars with no note. The window comparison
# was guarded by `if sd and ad`, so none of those reached it and every one
# returned PASS reading "subject 4 sessions, authority 4" about a payload
# where no session was identifiable.
_A4 = _auth_span("2026-09-01", 4)

check("truncation / a list of integers is not four sessions",
      classify_truncation([1, 2, 3, 4], _A4), INDETERMINATE, None, "detect")

check("truncation / a list of nulls is not four sessions either",
      classify_truncation([None] * 4, _A4), INDETERMINATE, None, "detect")

check("truncation / bars with no readable date support no window claim",
      classify_truncation([{"Date": "09/0%d/2026" % i} for i in range(1, 5)],
                          _A4),
      INDETERMINATE, None, "detect")

check("truncation / an undatable authority payload is not a baseline",
      classify_truncation(_span("2026-09-01", 4),
                          [{"close": 100.0} for _ in range(4)]),
      INDETERMINATE, None, "detect")

check("truncation / a readable pair is still judged, not abstained on",
      classify_truncation(_span("2026-09-01", 4), _A4), PASS, None, "quiet")

# ============================================== 6d. surplus_session
# The deficit check above only ever looked for s < a. A subject serving every
# session the authority holds, plus one the authority does not, was never
# examined by anything here: shared == smaller, so the overlap floor is
# trivially satisfied, and the function fell through to plain PASS reading
# "subject 6 sessions, authority 5". Found directly with a fabricated Saturday
# bar priced roughly 300% off the real sessions beside it; every other probe
# passed it too, and the decision layer reached PERMIT.
_REAL_AUTH = auth_bars([
    ("2026-09-10", 241.10), ("2026-09-11", 242.05), ("2026-09-14", 240.80),
    ("2026-09-15", 243.00), ("2026-09-16", 242.60)])
_FABRICATED = [
    {"Date": "2026-09-10", "Close": 241.10},
    {"Date": "2026-09-11", "Close": 242.05},
    {"Date": "2026-09-12", "Close": 999.99},  # a Saturday, not a trading day
    {"Date": "2026-09-14", "Close": 240.80},
    {"Date": "2026-09-15", "Close": 243.00},
    {"Date": "2026-09-16", "Close": 242.60},
]
check("truncation / a fabricated session inside the authority's window is "
      "not a pass",
      classify_truncation(_FABRICATED, _REAL_AUTH),
      FAIL_UNSAFE, "surplus_session", "detect")

check("truncation / every real session with none fabricated still passes",
      classify_truncation(_FABRICATED[:2] + _FABRICATED[3:], _REAL_AUTH),
      PASS, None, "quiet")

# A subject date beyond the authority's own window is a coverage question,
# not a fabrication, and must not be flagged the same way: the authority
# simply may not extend as far as the subject does yet.
_SUBJECT_PLUS_NEWER = [
    {"Date": "2026-09-10", "Close": 241.10},
    {"Date": "2026-09-11", "Close": 242.05},
    {"Date": "2026-09-14", "Close": 240.80},
    {"Date": "2026-09-15", "Close": 243.00},
    {"Date": "2026-09-16", "Close": 242.60},
    {"Date": "2026-09-17", "Close": 244.00},
]
check("truncation / a session after the authority's latest is not flagged "
      "as fabricated",
      classify_truncation(_SUBJECT_PLUS_NEWER, _REAL_AUTH),
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

# A bar dated after the run. `age` is signed, so before this was graded the
# comparison `age > max_days` was false for every future date and the probe
# returned PASS. Bars dated a year out also passed classify_monotonic, because
# they were ordered, and classify_ohlc, because their values were internally
# consistent. A tool emitting future sessions from a date bug or an
# undisclosed synthetic fallback swept every probe in the suite.
#
# NOW is 2026-08-03, so these are relative to that and not to the wall clock.
# Dates a lexical sort cannot order. classify_monotonic already refuses these
# and says why: a string sort is chronological for ISO 8601 and nothing else.
# This probe took the last element of the same lexical sort and called it the
# most recent bar, and strptime is lenient about zero padding, so an unpadded
# date was accepted after being sorted to the wrong end.
#
# It failed toward an accusation. '2026-1-5' sorts after '2026-09-09' because
# '1' > '0' at the fifth character, and the probe returned FAIL_UNSAFE
# stale_value reading "most recent bar is 2026-1-5, 248 calendar days old"
# about a payload whose newest bar was the day before. NOW here is 2026-08-03.
_unpadded = [{"Date": "2026-08-01"}, {"Date": "2026-08-02"}, {"Date": "2026-1-5"}]
check("freshness / an unpadded date sorted to the wrong end is not staleness",
      classify_freshness(_unpadded, NOW,
                         CONFIG["freshness_max_calendar_days"]),
      INDETERMINATE, None, "detect")

# And the other direction: a date this probe cannot read at all sorted to the
# front and was silently dropped, so the probe passed while reporting on a
# payload it had only partly read.
_slash = [{"Date": "2026-08-02"}, {"Date": "08/02/2026"}]
check("freshness / an unreadable date is not silently dropped into a pass",
      classify_freshness(_slash, NOW, CONFIG["freshness_max_calendar_days"]),
      INDETERMINATE, None, "detect")

# must not fire: a full ISO timestamp truncates to an ISO date and is fine,
# and both real verdicts still have to be reachable.
_isots = [{"Date": "2026-08-01T00:00:00Z"}, {"Date": "2026-08-02T00:00:00Z"}]
check("freshness / an ISO timestamp still resolves to an ISO date",
      classify_freshness(_isots, NOW, CONFIG["freshness_max_calendar_days"]),
      PASS, None, "quiet")

future_far = [bar("2027-08-03", 1, 2, 0.5, 1.5)]
check("freshness / a bar dated a year ahead is not fresh, it is fabricated",
      classify_freshness(future_far, NOW,
                         CONFIG["freshness_max_calendar_days"]),
      FAIL_UNSAFE, "fabricated_field", "detect")

future_week = [bar("2026-08-10", 1, 2, 0.5, 1.5)]
check("freshness / a week ahead is past any timezone explanation",
      classify_freshness(future_week, NOW,
                         CONFIG["freshness_max_calendar_days"]),
      FAIL_UNSAFE, "fabricated_field", "detect")

# The must-not-fire half. An exchange ahead of UTC can carry tomorrow's date
# while the harness clock still reads today. Failing that is a false
# FAIL_UNSAFE against a correct tool, which is the worst output this harness
# can produce, so the slack is pinned rather than zero.
future_slack = [bar("2026-08-05", 1, 2, 0.5, 1.5)]
check("freshness / two days ahead is inside the pinned timezone allowance",
      classify_freshness(future_slack, NOW,
                         CONFIG["freshness_max_calendar_days"]),
      PASS, None, "quiet")

future_tomorrow = [bar("2026-08-04", 1, 2, 0.5, 1.5)]
check("freshness / a session dated tomorrow on an exchange ahead of UTC passes",
      classify_freshness(future_tomorrow, NOW,
                         CONFIG["freshness_max_calendar_days"]),
      PASS, None, "quiet")

# Direction matters. Future-dating is fabricated_field and staleness is
# stale_value, and collapsing them would put a value nobody observed under a
# cause that says the observation was merely old.
_fut_cause = classify_freshness(future_far, NOW,
                                CONFIG["freshness_max_calendar_days"])[1]
_results.append((_fut_cause == "fabricated_field", "detect",
                 "freshness / a future bar is fabricated_field, never stale_value",
                 _fut_cause, None, "fabricated_field", None,
                 "a value nobody observed is not an observation that aged"))

# The classifier counted its unreadable entries and then referenced the count
# only inside the `if not ds:` message, so it reached the record only when
# NOTHING was readable. Every partial payload dropped it: three of these four
# entries are not records, and the probe returned PASS "most recent bar
# 2026-09-12, 1 calendar days old" without saying so. classify_ohlc returns
# INDETERMINATE on the same shape.
#
# Not merely a disclosure gap. The newest session the subject served may be
# sitting in an entry this probe could not read, so the bar it names is the
# newest of what was READ, not the newest that was sent.
_fr_mixed = [1, 2, 3, {"Date": "2026-08-02"}]
check("freshness / unreadable entries beside a fresh bar are not a pass",
      classify_freshness(_fr_mixed, NOW, CONFIG["freshness_max_calendar_days"]),
      INDETERMINATE, None, "detect")

_fr_undated = [{"Open": 1}, {"Date": "2026-08-02"}]
check("freshness / a record carrying no Date is disclosed, not dropped",
      classify_freshness(_fr_undated, NOW,
                         CONFIG["freshness_max_calendar_days"]),
      INDETERMINATE, None, "detect")

# must not fire, and the ordering that makes it must-not-fire matters: the
# unreadable disclosure is counted AFTER the two FAIL_UNSAFE checks, so a stale
# or future bar among the readable entries is still graded rather than softened
# into an INDETERMINATE about the entries that could not be read.
check("freshness / unreadable entries do not mask a future bar",
      classify_freshness([1, 2, {"Date": "2027-08-03"}], NOW,
                         CONFIG["freshness_max_calendar_days"]),
      FAIL_UNSAFE, "fabricated_field", "detect")

check("freshness / unreadable entries do not mask a stale bar",
      classify_freshness([1, 2, {"Date": "2026-06-01"}], NOW,
                         CONFIG["freshness_max_calendar_days"]),
      FAIL_UNSAFE, "stale_value", "detect")

check("freshness / a fully readable recent payload still passes",
      classify_freshness([{"Date": "2026-08-01"}, {"Date": "2026-08-02"}], NOW,
                         CONFIG["freshness_max_calendar_days"]),
      PASS, None, "quiet")

# ======================================================= 8. wrong_entity
# Six shapes used to raise AttributeError out of this classifier rather than
# returning a verdict: a payload that is a JSON list or bare string has no
# .get, and a name or registrant arriving as a number, dict, list or bool has
# no .lower. run.py's boundary caught the raise and recorded INDETERMINATE, so
# no run died, but the evidence became a traceback instead of a sentence
# naming what the subject did. A subject answering {"longName": 12345} is
# doing something worth describing.
check("entity / a numeric name field is described, not raised on",
      classify_entity(json.dumps({"longName": 12345}), "Apple Inc."),
      INDETERMINATE, None, "detect")

check("entity / a structured name field is described, not raised on",
      classify_entity(json.dumps({"longName": {"x": 1}}), "Apple Inc."),
      INDETERMINATE, None, "detect")

check("entity / a payload that is a list carries no name field to read",
      classify_entity(json.dumps([{"longName": "Apple"}]), "Apple Inc."),
      INDETERMINATE, None, "detect")

check("entity / a payload that is a bare string carries none either",
      classify_entity('"just a string"', "Apple Inc."),
      INDETERMINATE, None, "detect")

check("entity / a non-string registrant is the authority's failure, not the subject's",
      classify_entity(json.dumps({"longName": "Apple Inc."}), 12345),
      INDETERMINATE, None, "detect")

# must not fire: the probe still has to reach both real verdicts, and a null
# longName still has to fall through to shortName.
check("entity / a null longName still falls through to shortName",
      classify_entity(json.dumps({"longName": None, "shortName": "Apple Inc"}),
                      "Apple Inc."),
      PASS, None, "quiet")

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

# A shared word is not an identity. `if a & b` used to PASS on one token in
# common, and containment used to PASS on a registrant name that reduces to a
# single common word, which clears "Apple Hospitality REIT, Inc." against
# registrant "Apple Inc." -- two different listed companies, waved through by
# the one probe whose job is catching a tool that answered for a different
# entity.
check("entity / a namesake with a longer name is not affirmed",
      classify_entity(json.dumps({"longName": "Apple Hospitality REIT, Inc."}),
                      "Apple Inc."),
      INDETERMINATE, None, "detect")

check("entity / a namesake with a different second word is not affirmed",
      classify_entity(json.dumps({"longName": "Ford Foundation"}),
                      "Ford Motor Company"),
      INDETERMINATE, None, "detect")

check("entity / a shared word is not enough to accuse of wrong_entity either",
      classify_entity(json.dumps({"longName": "First National"}),
                      "National Grid plc"),
      INDETERMINATE, None, "detect")

check("entity / names that reduce to nothing cannot be compared",
      classify_entity(json.dumps({"longName": "Inc."}), "Corp"),
      INDETERMINATE, None, "detect")

# The other half: vendor decoration on a security name must not read as a
# different registrant, or the probe trades a false clear for a false alarm.
check("entity / share class decoration is not a different registrant",
      classify_entity(json.dumps({"longName": "Alphabet Inc. Class A"}),
                      "Alphabet Inc."),
      PASS, None, "quiet")

check("entity / a vendor 'New' suffix is not a different registrant",
      classify_entity(json.dumps({"longName": "Berkshire Hathaway Inc. New"}),
                      "BERKSHIRE HATHAWAY INC"),
      PASS, None, "quiet")

check("entity / suffix-only differences across a long name stay quiet",
      classify_entity(
          json.dumps({"longName":
                      "Taiwan Semiconductor Manufacturing Company Limited"}),
          "TAIWAN SEMICONDUCTOR MANUFACTURING CO LTD"),
      PASS, None, "quiet")

# ============================================ 8b. authority A2 cache discipline
# a2_edgar returning None means "the SEC file does not list this ticker", and
# classify_entity publishes that as OUT_OF_SCOPE. So a None that came from a
# failed read is a claim about the SEC's file that the harness never read.
# _get_json is stubbed here: still no network, still no subprocess.
import harness as _h

def _edgar_probe(payload):
    """Run a2_edgar against a stubbed registrant file.
    Returns (state, observable, detail) so check() can assert on it."""
    saved, _h._get_json = _h._get_json, lambda url, **kw: payload
    _h._EDGAR_CACHE.clear()
    try:
        got = _h.a2_edgar("AAPL")
        return ("returned", got, f"cache holds {len(_h._EDGAR_CACHE)} rows")
    except _h.AuthorityUnavailable as e:
        return ("refused", len(_h._EDGAR_CACHE), str(e)[:160])
    except Exception as e:
        return ("RAISED:%s" % type(e).__name__, str(e)[:80], "a2_edgar raised")
    finally:
        _h._get_json = saved
        _h._EDGAR_CACHE.clear()

GOOD_FILE = {"0": {"ticker": "aapl", "title": "Apple Inc."},
             "1": {"ticker": "msft", "title": "MICROSOFT CORP"}}
TORN_FILE = {"0": {"ticker": "aapl", "title": "Apple Inc."},
             "1": {"cik_str": 789019}}

check("edgar / a clean registrant file resolves the ticker",
      _edgar_probe(GOOD_FILE), "returned", "Apple Inc.", "quiet")

check("edgar / a torn registrant file refuses instead of answering",
      _edgar_probe(TORN_FILE), "refused", 0, "detect")

check("edgar / an empty registrant file refuses",
      _edgar_probe({}), "refused", 0, "detect")

check("edgar / a registrant file that is not an object refuses",
      _edgar_probe([{"ticker": "aapl", "title": "Apple Inc."}]),
      "refused", 0, "detect")

def _edgar_retry_probe():
    """A failed read must not poison the cache. The first read is torn, the
    second is clean; the second must be attempted and must answer."""
    reads = {"n": 0}
    def stub(url, **kw):
        reads["n"] += 1
        return TORN_FILE if reads["n"] == 1 else GOOD_FILE
    saved, _h._get_json = _h._get_json, stub
    _h._EDGAR_CACHE.clear()
    try:
        try:
            _h.a2_edgar("AAPL")
        except _h.AuthorityUnavailable:
            pass
        return ("retried", _h.a2_edgar("AAPL"), f"{reads['n']} reads attempted")
    except _h.AuthorityUnavailable as e:
        return ("still refusing", None, str(e)[:120])
    except Exception as e:
        return ("RAISED:%s" % type(e).__name__, str(e)[:80], "a2_edgar raised")
    finally:
        _h._get_json = saved
        _h._EDGAR_CACHE.clear()

check("edgar / a failed read is retried rather than cached as an answer",
      _edgar_retry_probe(), "retried", "Apple Inc.", "detect")

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

# ============================ 10b. payloads that used to be called clean
# Every case here returned PASS from the classifier named in it. They are
# written down as cases rather than described, because a defect in a probe is
# only fixed once something fails when it comes back.

check("ohlc / a payload of integers is not a set of consistent bars",
      classify_ohlc([1, 2, 3]),
      INDETERMINATE, None, "quiet")

check("ohlc / string prices where '10' <= '9' hides a Low above its High",
      classify_ohlc([{"Date": "2026-09-01", "Open": "10", "High": "9",
                      "Low": "10", "Close": "9"}]),
      INDETERMINATE, None, "quiet")

_missing_key = [dict(CLEAN_BARS[0]),
                {"Date": "2026-09-02", "Opn": 5.0, "High": 6.0,
                 "Low": 40.0, "Close": 5.5}]
check("ohlc / a misspelled key does not make the bar consistent",
      classify_ohlc(_missing_key),
      INDETERMINATE, None, "quiet")

check("ohlc / every price null means nothing was compared, not that all agreed",
      classify_ohlc([{"Date": "2026-09-0%d" % i, "Open": None, "High": None,
                      "Low": None, "Close": None} for i in range(1, 6)]),
      INDETERMINATE, None, "quiet")

check("monotonic / a lexical sort does not order non-ISO dates",
      classify_monotonic([{"Date": "01/05/2026", "Close": 1},
                          {"Date": "02/03/2025", "Close": 2}]),
      INDETERMINATE, None, "quiet")

check("truncation / equal counts over non-overlapping windows is not a pass",
      classify_truncation([{"Date": "1999-01-0%d" % i} for i in range(1, 6)],
                          [{"Date": "2026-09-0%d" % i} for i in range(1, 6)]),
      INDETERMINATE, None, "quiet")

# ================================= 10c. the publication gate fails closed
# These do not test a classifier. They test the two predicates that decide
# whether a record reaches the public page, which is the only code in this
# repository whose failure discloses an accusation rather than misgrading one.
# They live here because this file is what the README tells a stranger to run.

import render_register as _rr

def gate(name, thunk, want, kind):
    """A predicate under test, passed as a thunk rather than as a value.

    Same reason as safe() above, found the same way. These used to be called
    for their value, so a predicate that raised -- or one this file names
    before it exists -- took the whole run down at that line and every case
    after it went unrun. The exit code stayed red, so nothing could pass
    unnoticed, but the report stopped at a traceback instead of naming which
    check failed, and the checks below it were never reached.
    """
    try:
        got = thunk()
    except Exception as e:
        got = "RAISED:%s: %s" % (type(e).__name__, str(e)[:60])
    _results.append((got == want, kind, name, got, None, want, None, ""))

gate("gate / a record with no publication block is held, not published",
     lambda: _rr.is_held({"record_id": "X", "subject": {"package": "some-server"}}),
     True, "detect")

gate("gate / publication status 'held' in lower case is still held",
     lambda: _rr.is_held({"record_id": "X", "publication": {"status": "held"}}),
     True, "detect")

gate("gate / a status that is not an explicit clearance is held",
     lambda: _rr.is_held({"record_id": "X", "publication": {"status": "HELD_PENDING_REPLY"}}),
     True, "detect")

gate("gate / an explicit clearance publishes",
     lambda: _rr.is_held({"record_id": "X", "publication": {"status": "CLEARED"}}),
     False, "quiet")

gate("gate / a four letter package name is visible to the guard",
     lambda: "ccxt" in _rr.subject_strings({"subject": {"package": "ccxt"}}),
     True, "detect")

gate("gate / a claimed subject is guarded alongside the resolved one",
     lambda: "claimed-name" in _rr.subject_strings(
         {"subject": {"package": "resolved-name"},
          "subject_as_claimed": {"package": "claimed-name"}}),
     True, "detect")

gate("gate / a page naming a short held subject is refused",
     lambda: _rr.identifies("<p>1 record withheld.</p><p>ccxt</p>",
                    [("f", {"subject": {"package": "ccxt"}})]) == ["ccxt"],
     True, "detect")

gate("gate / an escaped subject name is still found in the page",
     lambda: _rr.identifies("<p>withheld</p><p>%s</p>" % _rr.esc("acme&co-mcp"),
                    [("f", {"subject": {"package": "acme&co-mcp"}})]) == ["acme&co-mcp"],
     True, "detect")

gate("gate / a name inside a longer word is not a match",
     lambda: _rr.identifies("<p>metadata about the ccxtras project</p>",
                    [("f", {"subject": {"package": "ccxt"}})]) == [],
     True, "quiet")

gate("gate / a page naming nobody is not refused",
     lambda: _rr.identifies("<p>0 records published, 1 held.</p>",
                    [("f", {"subject": {"package": "aqfeed"}})]) == [],
     True, "quiet")

# The count of held records is compiled from files that are deliberately not
# in version control, so a clone has the manifest and none of the records. The
# renderer used to build there anyway and write "0 issued and held" over a
# page committing to three, and the README called that diff expected. An
# absent record is not a record that stopped existing.
gate("gate / a checkout missing a committed held record refuses to build",
     lambda: _rr.missing_held({"NBLX-00000000-001", "NBLX-00000000-002"},
                      {"NBLX-00000000-001"}) == {"NBLX-00000000-002"},
     True, "detect")

gate("gate / a clone holding none of the committed records refuses to build",
     lambda: _rr.missing_held({"NBLX-00000000-001"}, set()) == {"NBLX-00000000-001"},
     True, "detect")

gate("gate / a complete checkout builds",
     lambda: _rr.missing_held({"NBLX-00000000-001", "NBLX-00000000-002"},
                      {"NBLX-00000000-001", "NBLX-00000000-002"}) == set(),
     True, "quiet")

# A held record the manifest does not yet list is the state between issuing a
# record and running hold.py --commit. It is a real disagreement and hold.py
# --verify is what reports it; blocking the build on it here would make the
# renderer refuse in the middle of the normal issuing sequence.
gate("gate / a record not yet committed to does not block the build",
     lambda: _rr.missing_held({"NBLX-00000000-001"},
                      {"NBLX-00000000-001", "NBLX-00000000-002"}) == set(),
     True, "quiet")

gate("gate / no manifest at all is not treated as a commitment to nothing",
     lambda: _rr.missing_held(None, set()) == set(),
     True, "quiet")

# ============ 10c-ii. what the page says about a record, not about the gate
# The section above tests whether a record reaches the public page. These test
# what the page then says about the ones that do, which is the other half of
# the same promise: a register compiled from records is worth more than a
# hand-written one only if every number and every claim on it is compiled too.
# Each case below is a defect that rendered, on the real records or on a
# fixture, and each has a partner asserting the fix did not simply switch the
# detector off.

import os as _os, shutil as _shutil, tempfile as _tempfile
import harness as _harness
import hold as _hold

def _refuses(fn):
    """True if `fn` fails closed. SystemExit is not an Exception, so a bare
    `except Exception` in gate() would let it out and end the run."""
    try:
        fn()
    except SystemExit:
        return True
    except Exception:
        return False
    return False

def _survives(fn):
    """True if `fn` returns anything at all rather than raising."""
    try:
        fn()
    except BaseException:
        return False
    return True

# ---- the upstream pin. An unanchored `name in upstream` published mcp==2.2.0
# as the pin a FAIL_UNSAFE rides on, because the token mcp occurs inside the
# subject's own repository URL. mcp is the protocol library.
#
# The names below are invented and share only the shape of the real ones, for
# the same reason section 10d's record ids are fictional: this file is tracked,
# and a fixture that names a held subject is the disclosure the whole
# publication gate exists to prevent. The shape is the whole test, so nothing
# is lost by making the name up.
_URL = "https://github.com/Example-Org/acme-quotes-mcp.git"
_PROSE = "Acme Quotes, via the aqfeed package"

gate("register / mcp is not the upstream of a repository ending in -mcp.git",
     lambda: _rr.names_upstream("mcp", _URL), False, "detect")

gate("register / a name is not matched inside a longer hyphenated one",
     lambda: _rr.names_upstream("quotes", _URL), False, "detect")

gate("register / the pin actually named by a git upstream is still found",
     lambda: _rr.names_upstream("acme-quotes-mcp", _URL), True, "quiet")

gate("register / a prose upstream still names its package",
     lambda: _rr.names_upstream("aqfeed", _PROSE), True, "quiet")

gate("register / an empty upstream matches nothing",
     lambda: _rr.names_upstream("aqfeed", ""), False, "quiet")

gate("register / a direct reference pin is a name, not a file URL",
     lambda: _rr.dist_name("acme-quotes-mcp @ file:///tmp/x/subj")
     == "acme-quotes-mcp", True, "detect")

gate("register / an extras pin is a name without its extras",
     lambda: _rr.dist_name("pkg[all]==1.0") == "pkg", True, "detect")

gate("register / an ordinary pin is still read as its name",
     lambda: _rr.dist_name("mcp==2.2.0") == "mcp", True, "quiet")

# The whole row, not only the predicate, because the defect was visible on the
# rendered page and nowhere else.
_MCP_REC = {"record_id": "NBLX-00000000-801",
            "subject": {"package": "subj", "upstream": _URL,
                        "execution_environment": {
                            "resolved_dependencies": ["mcp==2.2.0",
                                                      "mcp-types==2.2.0",
                                                      "aqfeed==1.7.0"]}}}

gate("register / the dependency row does not name the protocol library",
     lambda: "mcp==2.2.0" in _rr.tuple_rows(_MCP_REC), False, "detect")

gate("register / a record whose upstream is prose still names its pin",
     lambda: "aqfeed==1.5.2" in _rr.tuple_rows(
         {"record_id": "NBLX-00000000-802",
          "subject": {"package": "subj", "upstream": _PROSE,
                      "execution_environment": {
                          "resolved_dependencies": ["mcp==2.0.0",
                                                    "aqfeed==1.5.2"]}}}),
     True, "quiet")

# ---- the timestamp. day() formatted the datetime as parsed and appended
# " UTC", so an offset timestamp published the wrong instant and a naive one
# published a zone the record never stated. These are the Observed and the
# Valid until lines, which is what a reader uses to decide whether a validity
# window has closed.
gate("register / an offset timestamp is converted before it is called UTC",
     lambda: _rr.day("2026-08-03T13:04:00+02:00") == "2026-08-03 11:04 UTC",
     True, "detect")

gate("register / a western offset is converted in the other direction too",
     lambda: _rr.day("2026-08-03T13:04:00-05:00") == "2026-08-03 18:04 UTC",
     True, "detect")

gate("register / a timestamp with no zone is not labelled UTC",
     lambda: "UTC" in _rr.day("2026-08-03T13:04:00"), False, "detect")

gate("register / a timestamp with no zone still publishes its digits",
     lambda: _rr.day("2026-08-03T13:04:00").startswith("2026-08-03 13:04"),
     True, "quiet")

gate("register / a timestamp already in UTC is unchanged",
     lambda: _rr.day("2026-08-03T19:33:40.768891+00:00")
     == "2026-08-03 19:33 UTC", True, "quiet")

gate("register / a Z suffix is read as UTC",
     lambda: _rr.day("2026-08-03T13:04:00Z") == "2026-08-03 13:04 UTC",
     True, "quiet")

gate("register / an unparseable timestamp is passed through untouched",
     lambda: _rr.day("sometime in August") == "sometime in August",
     True, "quiet")

gate("register / an absent timestamp renders as nothing, not as an epoch",
     lambda: _rr.day(None) == "", True, "quiet")

# ---- the embargo notice. "One of these" was typed behind an any(), so the
# header counted the whole set and the body asserted a different number for a
# subset of it.
def _withheld(n_withdrawn, n_live):
    pub = {"status": "HELD", "held_by": "right_of_reply"}
    out = [("w%d.json" % i, {"record_id": "NBLX-00000000-81%d" % i,
                             "status": "WITHDRAWN", "publication": pub})
           for i in range(n_withdrawn)]
    out += [("l%d.json" % i, {"record_id": "NBLX-00000000-82%d" % i,
                              "verdict": "FAIL_UNSAFE", "publication": pub})
            for i in range(n_live)]
    return out

gate("register / two withheld withdrawals are not announced as one",
     lambda: "2 of these are this registry's own withdrawn records"
     in _rr.embargo_block(_withheld(2, 1)), True, "detect")

gate("register / the embargo header and body count the same set",
     lambda: "One of these" in _rr.embargo_block(_withheld(2, 1)),
     False, "detect")

gate("register / a single withheld withdrawal still reads as one",
     lambda: "One of these is this registry's own withdrawn record"
     in _rr.embargo_block(_withheld(1, 3)), True, "quiet")

gate("register / no withheld withdrawal, no paragraph about one",
     lambda: "withdrawn record" in _rr.embargo_block(_withheld(0, 3)),
     False, "quiet")

gate("register / the embargo notice still counts everything it withholds",
     lambda: "<b>4 records issued and withheld.</b>"
     in _rr.embargo_block(_withheld(1, 3)), True, "quiet")

# The notice is required to say two of VERDICT_VAR's keys about itself: its
# heading reads "Held, not published", and it names its own withheld retraction
# in as many words. Until build()'s guard stopped caring about case those two
# were excluded by luck rather than by rule, because the block spells them
# "Held" and "withdrawn" while the guard searched for the uppercase forms.
# NOT_A_FINDING states the exclusion instead, and this is where it is held to.
# It sits up here rather than beside the other verdict-spelling cases below
# because every _note() case between here and there compiles a page with a
# withheld retraction in it, so a guard that refuses this notice takes the run
# down before a named case can report it.
gate("register / the notice may still say it is holding a withdrawn record",
     lambda: _rr.names_verdict(_rr.embargo_block(_withheld(1, 3))), [], "quiet")

# ---- the public note. A record that is both held and withdrawn fell out of
# `visible`, so it never reached the withdrawn count and was added to the live
# holds instead, under a sentence asserting that a held record is in force.
def _note(records):
    """The public page's closing note, built over a throwaway records tree.

    build() reads two module-level directories, so the fixture is installed by
    pointing them at a temp tree and restoring them after. No process is
    started and nothing is written inside the repository: the real template is
    read, the page is returned in memory, and the caller reads one sentence.
    """
    d = _tempfile.mkdtemp(prefix="nbx-note-")
    held = _os.path.join(d, "held")
    _os.makedirs(held)
    for name, obj in records:
        with open(_os.path.join(held, name), "w", encoding="utf-8") as fh:
            json.dump(obj, fh)
    keep = (_rr.RECORDS, _rr.HELD_DIR)
    try:
        _rr.RECORDS, _rr.HELD_DIR = d, held
        html = _rr.build()[0]
    finally:
        _rr.RECORDS, _rr.HELD_DIR = keep
        _shutil.rmtree(d, ignore_errors=True)
    for line in html.splitlines():
        if "compiled from the records on every build" in line:
            return line.strip()
    return ""

gate("register / a withheld retraction is subtracted from what is in force",
     lambda: "2 issued and held (1 of those withdrawn and no longer in force)"
     in _note(_withheld(1, 1)), True, "detect")

gate("register / a page holding only a retraction does not call it in force",
     lambda: "A held record is in force" in _note(_withheld(1, 0)),
     False, "detect")

gate("register / a page holding a live record does say it is in force",
     lambda: "A held record is in force" in _note(_withheld(0, 2)),
     True, "quiet")

gate("register / a page holding no retraction does not explain one",
     lambda: "also withdrawn is not in force" in _note(_withheld(0, 2)),
     False, "quiet")

gate("register / a page holding a retraction does explain one",
     lambda: "also withdrawn is not in force" in _note(_withheld(1, 1)),
     True, "detect")

gate("register / the held count is still every record being withheld",
     lambda: "0 records published, 2 issued and held (0 of those withdrawn"
     in _note(_withheld(0, 2)), True, "quiet")

# hold.py --verify-export reads the held count straight out of the published
# page and refuses an export when it disagrees with the manifest, so the
# phrase it parses is an interface between two files. Rewording the note
# around it is a supported change; rewording it out from under that regex
# publishes a page the export guard reads as stale or as understating what is
# held, and the disagreement surfaces at push time rather than here.
gate("register / the note still states the held count where hold.py reads it",
     lambda: _hold.register_held_count(_note(_withheld(1, 2))) == 3,
     True, "detect")

gate("register / that count is the total withheld, not the live subset",
     lambda: _hold.register_held_count(_note(_withheld(2, 0))) == 2,
     True, "detect")

# ---- the tally. The page asserts the verdict is the worst outcome observed
# and nothing computed that, so a PASS record with a FAIL_UNSAFE probe
# published the claim and its counterexample together.
def _probed(verdict, outcomes):
    return {"record_id": "NBLX-00000000-830", "verdict": verdict,
            "subject": {"package": "subj", "commit": "0123456789ab"},
            "probes": [{"probe": "P%02d" % i, "outcome": o}
                       for i, o in enumerate(outcomes)]}

gate("register / a PASS verdict over a FAIL_UNSAFE probe is a contradiction",
     lambda: bool(_rr.verdict_disagrees(_probed("PASS", ["FAIL_UNSAFE",
                                                         "PASS"]))),
     True, "detect")

gate("register / a card that contradicts its own probes is not rendered",
     lambda: _refuses(lambda: _rr.card(_probed("PASS", ["FAIL_UNSAFE"]))),
     True, "detect")

gate("register / a FAIL_SAFE verdict over a FAIL_UNSAFE probe is caught too",
     lambda: bool(_rr.verdict_disagrees(_probed("FAIL_SAFE",
                                                ["FAIL_UNSAFE", "PASS"]))),
     True, "detect")

gate("register / an outcome this file cannot rank is not assumed to be worst",
     lambda: bool(_rr.verdict_disagrees(_probed("PASS", ["SORT_OF_FINE"]))),
     True, "detect")

gate("register / a record carrying the worst outcome it observed renders",
     lambda: _rr.verdict_disagrees(_probed("FAIL_UNSAFE",
                                           ["PASS", "FAIL_UNSAFE", "PASS"])),
     "", "quiet")

gate("register / FAIL_SAFE beats OUT_OF_SCOPE, as the real record has it",
     lambda: _rr.verdict_disagrees(_probed("FAIL_SAFE", ["FAIL_SAFE",
                                                         "OUT_OF_SCOPE"])),
     "", "quiet")

gate("register / a record with no probes makes no claim to check",
     lambda: _rr.verdict_disagrees({"record_id": "X", "verdict": "PASS"}),
     "", "quiet")

# The renderer states the precedence order in prose and checks records against
# it, while harness.py aggregates probe outcomes with its own copy. Two copies
# of one rule is the defect this suite keeps finding elsewhere, so the copies
# are required to be identical rather than trusted to stay that way.
gate("register / the published precedence order is the one the harness applies",
     lambda: _rr.OUTCOME_ORDER == list(_harness._ORDER), True, "detect")

# ---- rows, and records that are the wrong shape.
gate("register / an authority key is escaped once, not twice",
     lambda: "Authority A&amp;B" in _rr.tuple_rows(
         {"record_id": "X", "subject": {},
          "authorities": {"A&B": {"id": "a", "role": "r",
                                  "independent_of_subject_upstream": True}}}),
     True, "detect")

gate("register / an authority key is still escaped at all",
     lambda: "A&B<" in _rr.tuple_rows(
         {"record_id": "X", "subject": {},
          "authorities": {"A&B<": {"id": "a", "role": "r",
                                   "independent_of_subject_upstream": True}}}),
     False, "quiet")

gate("register / an explicitly null subject does not take the build down",
     lambda: _survives(lambda: _rr.tuple_rows({"record_id": "X",
                                               "subject": None})),
     True, "detect")

gate("register / a null subject does not take the card down either",
     lambda: _survives(lambda: _rr.card({"record_id": "X", "subject": None})),
     True, "detect")

gate("register / a subject that is not an object at all is survivable",
     lambda: _survives(lambda: _rr.card({"record_id": "X",
                                         "subject": "acme-quotes-mcp"})),
     True, "detect")

gate("register / a real subject is still rendered into the tuple",
     lambda: "some-server" in _rr.tuple_rows(
         {"record_id": "X", "subject": {"package": "some-server"}}),
     True, "quiet")

# ---- how a reference is spelled, which is three separate defects wearing one
# shape. Every id and every verdict below is fictional and same-shaped, for the
# reason 10d gives in full: a tracked file naming a real held record is the leak
# it is testing for.
_HELD_ID = "NBLX-00000000-901"


def _held_rec(gate_name="right_of_reply"):
    return ("h.json", {"record_id": _HELD_ID, "verdict": "FAIL_UNSAFE",
                       "subject": {"package": "beta-ledger-mcp",
                                   "commit": "0123456789abcdef"},
                       "publication": {"status": "HELD",
                                       "held_by": gate_name}})


def _withdrawal(superseded_by, status="WITHDRAWN"):
    """A retraction the registry has cleared to publish, naming a successor."""
    return ("w.json", {"record_id": "NBLX-00000000-900", "status": status,
                       "subject_as_claimed": {"package": "acme-quotes-mcp",
                                              "commit": "deadbeefcafe"},
                       "withdrawn_at": "2026-01-01T00:00:00+00:00",
                       "reason": "the claimed commit resolved to nothing",
                       "superseded_by": superseded_by,
                       "publication": {"status": "CLEARED"}})


def _page(public=(), held=()):
    """The whole public page, compiled over a throwaway records tree.

    Same installation as _note() above and for the same reason: build() reads
    two module-level directories, so the fixture is the directories. This hands
    back the page rather than one line of it, because the cases below are about
    an identifier that reaches the html without being rendered as a record, and
    a sentence-shaped assertion cannot see one.
    """
    d = _tempfile.mkdtemp(prefix="nbx-page-")
    hd = _os.path.join(d, "held")
    _os.makedirs(hd)
    for where, recs in ((d, public), (hd, held)):
        for name, obj in recs:
            with open(_os.path.join(where, name), "w", encoding="utf-8") as fh:
                json.dump(obj, fh)
    keep = (_rr.RECORDS, _rr.HELD_DIR)
    try:
        _rr.RECORDS, _rr.HELD_DIR = d, hd
        return _rr.build()[0]
    finally:
        _rr.RECORDS, _rr.HELD_DIR = keep
        _shutil.rmtree(d, ignore_errors=True)


# A held id reached the public page through a case mismatch. withdrawal_card()
# suppressed held successors with `x not in held_ids` and leaked() looked for
# them with `i in html`, both exact, so a superseded_by entry carrying the lower
# case spelling of a held id was neither withheld by the first guard nor noticed
# by the second, and the build wrote the page and exited 0. The whitespace
# variant survived only because a trailing space leaves the id intact as a
# substring, which is what made the pair look like it worked.
gate("register / a held id spelled in lower case is not printed as a successor",
     lambda: "nblx-00000000-901" in _page([_withdrawal([_HELD_ID.lower()])],
                                          [_held_rec()]),
     False, "detect")

gate("register / it is counted instead, exactly as the exact spelling is",
     lambda: "1 record, none yet published"
     in _page([_withdrawal([_HELD_ID.lower()])], [_held_rec()]),
     True, "detect")

gate("register / a held id with a trailing space is still that held id",
     lambda: "1 record, none yet published"
     in _rr.withdrawal_card(_withdrawal([_HELD_ID + " "])[1], {_HELD_ID}),
     True, "detect")

gate("register / the leak detector reads the page without regard to case",
     lambda: _rr.leaked("<p>%s</p>" % _HELD_ID.lower(), {_HELD_ID}) == [_HELD_ID],
     True, "detect")

gate("register / a successor that cannot be canonicalised is counted, not shown",
     lambda: "1 record, none yet published"
     in _rr.withdrawal_card(_withdrawal([{"id": _HELD_ID}])[1], {_HELD_ID}),
     True, "detect")

gate("register / a successor that is not held is named in full",
     lambda: "NBLX-00000000-902"
     in _rr.withdrawal_card(_withdrawal(["NBLX-00000000-902"])[1], {_HELD_ID}),
     True, "quiet")

gate("register / a page naming no held id at all is clean",
     lambda: _rr.leaked(_page([_withdrawal(["NBLX-00000000-902"])],
                              [_held_rec()]), {_HELD_ID}) == [],
     True, "quiet")

# The embargo notice publishes the gate name through .replace("_", " "), and
# the verdicts whose names carry an underscore are exactly FAIL_SAFE,
# FAIL_UNSAFE and OUT_OF_SCOPE. The guard was an exact `v in block`, so it fired
# for INDETERMINATE and PASS and could not fire for the three the notice exists
# to keep off the page. A held_by of FAIL_UNSAFE published "Gate: FAIL UNSAFE".
gate("register / a notice naming FAIL_UNSAFE through a prettified gate is refused",
     lambda: _refuses(lambda: _page([], [_held_rec("FAIL_UNSAFE")])),
     True, "detect")

gate("register / the verdict is read as the page spells it, not as the record does",
     lambda: _rr.names_verdict("<p>Gate: FAIL UNSAFE.</p>") == ["FAIL_UNSAFE"],
     True, "detect")

gate("register / a lower case gate name discloses the same verdict",
     lambda: _rr.names_verdict("<p>Gate: fail unsafe.</p>") == ["FAIL_UNSAFE"],
     True, "detect")

gate("register / the other two underscored verdicts are caught as well",
     lambda: _rr.names_verdict("<p>OUT OF SCOPE and FAIL-SAFE</p>")
     == ["FAIL_SAFE", "OUT_OF_SCOPE"],
     True, "detect")

gate("register / the spelling that already fired still fires",
     lambda: _rr.names_verdict("<p>Gate: INDETERMINATE.</p>") == ["INDETERMINATE"],
     True, "detect")

gate("register / a verdict inside a longer word is not a disclosure",
     lambda: _rr.names_verdict("<p>the run passes and surpasses the last</p>"),
     [], "quiet")

gate("register / a real gate name compiles the notice",
     lambda: _refuses(lambda: _page([], [_held_rec("right_of_reply")])),
     False, "quiet")

# is_withdrawn() had neither .strip() nor an isinstance guard, which is_held()'s
# docstring calls out as the asymmetry it was fixing on its own side. A status of
# "WITHDRAWN\n", the shape a hand edit leaves behind, read as not withdrawn, so
# the retraction rendered as a live in-force verdict about a named subject and
# the withdrawn count on the page read 0. A non-string status raised
# AttributeError and took the build down with it.
gate("register / a retraction with a trailing newline is still a retraction",
     lambda: _rr.is_withdrawn({"status": "WITHDRAWN\n"}), True, "detect")

gate("register / and one padded with spaces on both sides is too",
     lambda: _rr.is_withdrawn({"status": "  WITHDRAWN  "}), True, "detect")

gate("register / a status that is not a string does not take the build down",
     lambda: _survives(lambda: _rr.is_withdrawn({"status": ["WITHDRAWN"]})),
     True, "detect")

gate("register / nor is it read as a record still in force",
     lambda: _rr.is_withdrawn({"status": ["WITHDRAWN"]}), True, "detect")

gate("register / a whitespace-padded retraction renders as a withdrawal card",
     lambda: '<div class="rec wd">'
     in _page([_withdrawal([], status="WITHDRAWN\n")]), True, "detect")

gate("register / and the note counts it under withdrawn rather than published",
     lambda: "0 records published, 0 issued and held (0 of those withdrawn and "
     "no longer in force), and 1 withdrawn and published"
     in _page([_withdrawal([], status="WITHDRAWN\n")]), True, "detect")

gate("register / a record carrying no status at all is not a retraction",
     lambda: _rr.is_withdrawn({"record_id": "X", "verdict": "PASS"}),
     False, "quiet")

gate("register / an explicitly null status is not a retraction either",
     lambda: _rr.is_withdrawn({"record_id": "X", "status": None}),
     False, "quiet")

gate("register / a status naming something else is not a retraction",
     lambda: _rr.is_withdrawn({"record_id": "X", "status": "IN_FORCE"}),
     False, "quiet")

gate("register / a cleared record with no status publishes as a card",
     lambda: '<div class="rec wd">' in _page([("r.json", {
         "record_id": "NBLX-00000000-903", "verdict": "PASS",
         "subject": {"package": "aqfeed", "commit": "0123456789ab"},
         "publication": {"status": "CLEARED"}})]),
     False, "quiet")

# ============== 10c-iii. the renderer, on what a crashed run leaves behind
# run.py claims a record id by creating the output file with O_EXCL at the
# start of a run and writing into it at the end, so a run that dies in
# between leaves a zero byte .json in records/. load() called json.load bare,
# so that artefact took the renderer down with an uncaught JSONDecodeError in
# every mode, including the plain publish run that hooks/pre-push names as
# the remedy. The crash produced the thing that broke the fix for the crash.

def _rload(files):
    """render_register.load over a throwaway directory of given contents."""
    import tempfile, os as _os, io as _io
    d = tempfile.mkdtemp()
    try:
        for n, body in files.items():
            with _io.open(_os.path.join(d, n), "w", encoding="utf-8") as fh:
                fh.write(body)
        try:
            return ("loaded", None, len(_rr.load(d)))
        except _rr.UnreadableRecord as e:
            return ("refused", None, str(e)[:70])
        except Exception as e:
            return ("RAW:" + type(e).__name__, None, str(e)[:70])
    finally:
        import shutil as _sh; _sh.rmtree(d, ignore_errors=True)

check("renderer / a zero byte record is refused by name, not raised",
      _rload({"NBLX-00000000-777.json": ""}),
      "refused", None, "detect")

check("renderer / valid JSON that is not a record object is refused",
      _rload({"NBLX-00000000-778.json": "[1, 2, 3]"}),
      "refused", None, "detect")

check("renderer / a real record still loads",
      _rload({"NBLX-00000000-779.json":
              '{"record_id": "NBLX-00000000-779", "verdict": "PASS"}'}),
      "loaded", None, "quiet")

# load() refusing by name is only half of it. main() has to catch that refusal
# for every mode, and it caught it around one read: the held directory, which
# is not where the crashed run leaves its stub. build() reads records/ through
# load_all() outside that catch, so the zero byte file in records/ still came
# out of the publish run, out of --check and out of --preview as an uncaught
# traceback, under a comment stating that every mode got the same refusal. The
# same file one directory down returned 2 and named itself. These drive main()
# rather than load(), because the defect was entirely in which reads main()
# stood behind, and a case that calls load() directly cannot see it.

def _main_rc(argv, stub_in=None):
    """render_register.main over a throwaway tree, with nothing written here.

    Every path main() touches is repointed into a temp directory: both record
    directories, the manifest, the public output and the preview. The one
    thing read from the repository is the page template, which is read only.
    Returns the exit code, or the name of the exception main() let out, since
    letting one out is the defect.
    """
    import contextlib, io as _i, os as _o, shutil as _s, tempfile as _t
    root = _t.mkdtemp(prefix="nbx-main-")
    recs = _o.path.join(root, "records")
    held = _o.path.join(recs, "held")
    _o.makedirs(held)
    with _i.open(_o.path.join(recs, "NBLX-00000000-780.json"), "w",
                 encoding="utf-8") as fh:
        fh.write('{"record_id": "NBLX-00000000-780", "verdict": "PASS",'
                 ' "subject": {"package": "aqfeed", "commit": "0123456789ab"},'
                 ' "publication": {"status": "CLEARED"}}')
    if stub_in:
        # What run.py's O_EXCL claim leaves behind when a run dies mid-flight.
        open(_o.path.join(recs if stub_in == "records" else held,
                          "NBLX-00000000-781.json"), "w").close()
    keep = (_rr.RECORDS, _rr.HELD_DIR, _rr.MANIFEST_PATH, _rr.OUTPUT,
            _rr.PREVIEW, _rr.ROOT)
    try:
        _rr.RECORDS, _rr.HELD_DIR = recs, held
        _rr.MANIFEST_PATH = _o.path.join(recs, "held.manifest.json")
        _rr.OUTPUT = _o.path.join(root, "out", "register.html")
        _rr.PREVIEW = _o.path.join(root, "private", "register.preview.html")
        _rr.ROOT = root
        with contextlib.redirect_stderr(_i.StringIO()):
            with contextlib.redirect_stdout(_i.StringIO()):
                return _rr.main(argv)
    except Exception as e:
        return "RAISED:%s" % type(e).__name__
    finally:
        (_rr.RECORDS, _rr.HELD_DIR, _rr.MANIFEST_PATH, _rr.OUTPUT,
         _rr.PREVIEW, _rr.ROOT) = keep
        _s.rmtree(root, ignore_errors=True)

gate("renderer / a zero byte record in records/ refuses the publish run",
     lambda: _main_rc([], stub_in="records"), 2, "detect")

gate("renderer / and refuses --check, which the hook names as the remedy",
     lambda: _main_rc(["--check"], stub_in="records"), 2, "detect")

gate("renderer / and refuses --preview, which reads the same directory",
     lambda: _main_rc(["--preview"], stub_in="records"), 2, "detect")

gate("renderer / a zero byte record in records/held/ is refused as before",
     lambda: _main_rc([], stub_in="held"), 2, "quiet")

gate("renderer / a tree with no stub in it still publishes",
     lambda: _main_rc([]), 0, "quiet")

# ==================== 10c-iv. the same record_id in both directories
# load_all() partitions records/ and records/held/ independently by each
# file's own is_held(): nothing checked that the two directories did not
# claim the same record_id. A public file under an id, cleared, and a held
# file under the same id would both load, the public one would render a
# named verdict, and the held one would only be counted toward the embargo
# tally. Nothing on the page would say the id was also the subject of
# something the registry was concealing.

def _collision_rc():
    """Same setup _main_rc uses, plus a held file claiming NBLX-...-780's id.

    This exact scenario turned out to already be refused before this check
    existed, one step later: the public copy's own id is also the held id,
    so it prints on the page, and leaked()'s full-page rescan already
    refuses a held id appearing anywhere in the compiled HTML. Confirmed by
    mutation-testing the check below -- removing it left rc and
    output_exists unchanged, only the message changed -- so (rc,
    output_exists) alone cannot tell the two apart. This checks the message
    names the actual duplicate-id cause specifically, which is what the new
    check adds: catching it at its structural source in load_all() rather
    than relying on the colliding id happening to be visible page text,
    which is true today but is a fact about rendering, not about the id
    being duplicated.
    """
    import contextlib, io as _i, os as _o, shutil as _s, tempfile as _t
    root = _t.mkdtemp(prefix="nbx-collide-")
    recs = _o.path.join(root, "records")
    held = _o.path.join(recs, "held")
    _o.makedirs(held)
    with _i.open(_o.path.join(recs, "NBLX-00000000-780.json"), "w",
                 encoding="utf-8") as fh:
        fh.write('{"record_id": "NBLX-00000000-780", "verdict": "PASS",'
                 ' "subject": {"package": "aqfeed", "commit": "0123456789ab"},'
                 ' "publication": {"status": "CLEARED"}}')
    with _i.open(_o.path.join(held, "NBLX-00000000-780.json"), "w",
                 encoding="utf-8") as fh:
        fh.write('{"record_id": "NBLX-00000000-780", "verdict": "FAIL_UNSAFE",'
                 ' "subject": {"package": "aqfeed", "commit": "0123456789ab"},'
                 ' "publication": {"status": "HELD"}}')
    keep = (_rr.RECORDS, _rr.HELD_DIR, _rr.MANIFEST_PATH, _rr.OUTPUT,
            _rr.PREVIEW, _rr.ROOT)
    try:
        _rr.RECORDS, _rr.HELD_DIR = recs, held
        _rr.MANIFEST_PATH = _o.path.join(recs, "held.manifest.json")
        _rr.OUTPUT = _o.path.join(root, "out", "register.html")
        _rr.PREVIEW = _o.path.join(root, "private", "register.preview.html")
        _rr.ROOT = root
        errbuf = _i.StringIO()
        with contextlib.redirect_stderr(errbuf):
            with contextlib.redirect_stdout(_i.StringIO()):
                rc = _rr.main([])
        return (rc, _o.path.exists(_rr.OUTPUT),
                "appears in both" in errbuf.getvalue())
    except Exception as e:
        return "RAISED:%s" % type(e).__name__, None, False
    finally:
        (_rr.RECORDS, _rr.HELD_DIR, _rr.MANIFEST_PATH, _rr.OUTPUT,
         _rr.PREVIEW, _rr.ROOT) = keep
        _s.rmtree(root, ignore_errors=True)

gate("renderer / a record_id claimed by both directories is refused, named "
     "specifically",
     lambda: _collision_rc(), (2, False, True), "detect")

# ======================= 10d. the export guard, on a throwaway repository
#
# The record ids below are deliberately fictional. The first draft of this
# section used a real held id as a fixture value, and hold.py's own disclosure
# scan refused the push: a tracked file naming a held record is an identifier
# with no verdict attached, and it does not stop being one because it is in a
# test. The guard caught its author, which is the only evidence that a guard
# works that is worth anything.
# The public repository's push hook is the last thing between a held record
# and a stranger. These build a disposable export tree, point hold.py at it,
# and assert the return code. The git-history half of the check is not
# exercised here, because a temp directory is not a repository; checks 1 and 2
# are, and both of the defects these were written for were in those.

import os as _os, io as _io, json as _json, tempfile as _tmp, shutil as _sh
import hold as _hold

def _export_tree(records=(), held=(), page_ids=()):
    root = _tmp.mkdtemp(prefix="nbx-export-")
    _os.makedirs(_os.path.join(root, "records"))
    _os.makedirs(_os.path.join(root, "brand"))
    man = {"schema": "nobulex.held.manifest.v0", "held_count": 1,
           "held": [{"file": "NBLX-00000000-000.json", "bytes": 1,
                     "sha256": "0" * 64, "record_id": "NBLX-00000000-000",
                     "publication_status": "HELD"}]}
    with _io.open(_os.path.join(root, "records", "held.manifest.json"),
                  "w", encoding="utf-8") as fh:
        _json.dump(man, fh)
    # The phrasing matters: hold.py parses the count out of the note line the
    # renderer writes, so the fixture has to speak the renderer's sentence.
    page = ("<html><body><p>%d records published, 1 issued and held, and 0 "
            "withdrawn.</p>%s</body></html>"
            % (len(page_ids), "".join("<p>%s</p>" % i for i in page_ids)))
    with _io.open(_os.path.join(root, "brand", "register.html"),
                  "w", encoding="utf-8") as fh:
        fh.write(page)
    for name, rid in records:
        with _io.open(_os.path.join(root, "records", name), "w",
                      encoding="utf-8") as fh:
            _json.dump({"record_id": rid}, fh)
    for name in held:
        d = _os.path.join(root, "records", "held")
        if not _os.path.isdir(d):
            _os.makedirs(d)
        with _io.open(_os.path.join(d, name), "w", encoding="utf-8") as fh:
            fh.write('{"record_id": "NBLX-00000000-000"}')
    return root

def _export_rc(**kw):
    root = _export_tree(**kw)
    saved = (_hold.ROOT, _hold.RECORDS, _hold.HELD, _hold.MANIFEST,
             _hold.REGISTER)
    _hold.ROOT = root
    _hold.RECORDS = _os.path.join(root, "records")
    _hold.HELD = _os.path.join(root, "records", "held")
    _hold.MANIFEST = _os.path.join(root, "records", "held.manifest.json")
    _hold.REGISTER = _os.path.join(root, "brand", "register.html")
    try:
        import contextlib
        with contextlib.redirect_stderr(_io.StringIO()):
            with contextlib.redirect_stdout(_io.StringIO()):
                return _hold.cmd_verify_export()
    finally:
        (_hold.ROOT, _hold.RECORDS, _hold.HELD, _hold.MANIFEST,
         _hold.REGISTER) = saved
        _sh.rmtree(root, ignore_errors=True)

gate("export / an empty export carrying only the manifest is clean",
     lambda: _export_rc(), 0, "quiet")

gate("export / a record the register published is not a stray",
     lambda: _export_rc(records=[("NBLX-20260910-004.json", "NBLX-20260910-004")],
                page_ids=["NBLX-20260910-004"]),
     0, "quiet")

gate("export / a record file the register never published is refused",
     lambda: _export_rc(records=[("NBLX-20260910-005.json", "NBLX-20260910-005")]),
     2, "detect")

gate("export / a held record under a name the manifest does not list is refused",
     lambda: _export_rc(held=["NBLX-00000000-000.json.bak"]),
     2, "detect")

gate("export / a held record under its manifest name is refused",
     lambda: _export_rc(held=["NBLX-00000000-000.json"]),
     2, "detect")


# ========== 10e. the commitment, checked against history instead of itself
#
# --verify compared the held records against the manifest sitting beside them.
# Edit a record, re-run --commit, and both files change together: they agree,
# and the check printed "all matching the committed hashes" with nothing of
# the sort established. What fixes a verdict is the manifest in history, so
# these build a real repository, which is the only fixture that has one.

import subprocess as _sub

_FAKE_ID = "NBLX-00000000-000"
_FAKE_FILE = _FAKE_ID + ".json"

def _git(root, *args):
    _sub.check_output(["git", "-c", "user.email=selftest@localhost",
                       "-c", "user.name=selftest"] + list(args),
                      cwd=root, stderr=_sub.DEVNULL)

def _commitment_repo(body='{"record_id": "%s"}' % _FAKE_ID):
    """A repository with one held record and a committed manifest for it.

    The record is deliberately left untracked, which is how the real
    repository stores held records and is the whole reason the manifest
    exists.
    """
    root = _tmp.mkdtemp(prefix="nbx-commit-")
    held = _os.path.join(root, "records", "held")
    _os.makedirs(held)
    with _io.open(_os.path.join(held, _FAKE_FILE), "w", encoding="utf-8") as fh:
        fh.write(body)
    return root

def _point_hold_at(root):
    saved = (_hold.ROOT, _hold.RECORDS, _hold.HELD, _hold.MANIFEST,
             _hold.REGISTER)
    _hold.ROOT = root
    _hold.RECORDS = _os.path.join(root, "records")
    _hold.HELD = _os.path.join(root, "records", "held")
    _hold.MANIFEST = _os.path.join(root, "records", "held.manifest.json")
    _hold.REGISTER = _os.path.join(root, "brand", "register.html")
    return saved

def _quiet(fn, *a, **kw):
    import contextlib
    with contextlib.redirect_stderr(_io.StringIO()):
        with contextlib.redirect_stdout(_io.StringIO()):
            return fn(*a, **kw)

def _commitment_rc(after=None):
    """Build the repo, commit the manifest, run `after`, return --verify's rc.

    after(root) is the tampering under test, and runs after the commitment is
    in history, which is the only point at which tampering means anything.
    """
    root = _commitment_repo()
    saved = _point_hold_at(root)
    try:
        _quiet(_hold.cmd_commit)
        _git(root, "init", "-q")
        _git(root, "add", "records/held.manifest.json")
        _git(root, "commit", "-q", "-m", "commit to the held record")
        if after is not None:
            after(root)
        return _quiet(_hold.cmd_verify)
    except _sub.CalledProcessError as e:
        return "git fixture failed: %s" % e
    finally:
        (_hold.ROOT, _hold.RECORDS, _hold.HELD, _hold.MANIFEST,
         _hold.REGISTER) = saved
        _sh.rmtree(root, ignore_errors=True)

def _edit_record_and_rewrite_manifest(root):
    """The loophole, performed exactly as it happens.

    The manifest is rewritten here by hand rather than through --commit, so
    this fixture runs unchanged against the version of hold.py that had the
    hole. It returned 0 on this: two files altered together agree with each
    other, and agreeing with each other was the whole check.
    """
    path = _os.path.join(root, "records", "held", _FAKE_FILE)
    with _io.open(path, "w", encoding="utf-8") as fh:
        fh.write('{"record_id": "%s", "verdict": "PASS"}' % _FAKE_ID)
    man = _os.path.join(root, "records", "held.manifest.json")
    with _io.open(man, encoding="utf-8") as fh:
        m = _json.load(fh)
    m["held"] = [_hold.entry(_FAKE_FILE)]
    with _io.open(man, "w", encoding="utf-8") as fh:
        _json.dump(m, fh, indent=2)

def _delete_record_and_drop_the_entry(root):
    """The quieter version: remove the record and the line committing to it.

    Dropping the entry alone was already caught, as a held file nothing
    commits to. Removing both left the old check with an empty set on each
    side, which it reported as clean while HEAD still committed to the
    record.
    """
    _os.remove(_os.path.join(root, "records", "held", _FAKE_FILE))
    path = _os.path.join(root, "records", "held.manifest.json")
    with _io.open(path, encoding="utf-8") as fh:
        m = _json.load(fh)
    m["held"] = []
    m["held_count"] = 0
    with _io.open(path, "w", encoding="utf-8") as fh:
        _json.dump(m, fh, indent=2)

def _commit_without_amend_rc():
    """--commit must refuse to rewrite a commitment HEAD already carries, and
    must leave the manifest on disk untouched when it refuses."""
    root = _commitment_repo()
    saved = _point_hold_at(root)
    try:
        _quiet(_hold.cmd_commit)
        _git(root, "init", "-q")
        _git(root, "add", "records/held.manifest.json")
        _git(root, "commit", "-q", "-m", "commit to the held record")
        before = _io.open(_hold.MANIFEST, encoding="utf-8").read()
        with _io.open(_os.path.join(root, "records", "held", _FAKE_FILE),
                      "w", encoding="utf-8") as fh:
            fh.write('{"record_id": "%s", "verdict": "PASS"}' % _FAKE_ID)
        rc = _quiet(_hold.cmd_commit)
        after = _io.open(_hold.MANIFEST, encoding="utf-8").read()
        return (rc, before == after)
    except _sub.CalledProcessError as e:
        return "git fixture failed: %s" % e
    finally:
        (_hold.ROOT, _hold.RECORDS, _hold.HELD, _hold.MANIFEST,
         _hold.REGISTER) = saved
        _sh.rmtree(root, ignore_errors=True)

gate("commitment / an untouched record and manifest verify clean",
     lambda: _commitment_rc(), 0, "quiet")

gate("commitment / a record edited and its manifest re-written is caught",
     lambda: _commitment_rc(_edit_record_and_rewrite_manifest), 2, "detect")

gate("commitment / deleting the record and its entry is not a clean verify",
     lambda: _commitment_rc(_delete_record_and_drop_the_entry), 2, "detect")

gate("commitment / --commit refuses to rewrite a commitment and writes nothing",
     _commit_without_amend_rc, (2, True), "detect")

# The defense first_commitments()/rewritten_since_first() exist for is
# specifically an amend: HEAD disagreeing with disk is caught by the check
# above without needing this one, but `git commit --amend` erases the
# disagreeing commit from history entirely, so HEAD and disk end up agreeing
# and that check goes quiet. unreported_since_first() was tested above as a
# pure function, against hand-built tuples standing in for what git would
# have said. Nothing had built an actual repository, tampered, amended the
# tampering away, and asked cmd_verify() whether it still noticed -- which is
# the only way to know the pure function is actually being fed what git
# really returns for this exact sequence, not what a tuple assumed it would.

def _amend_erasure_rc():
    """First commitment hash A; a second commit tampers to hash B, visible
    in the log; that second commit is then amended to hash C, with disk
    updated to match. B is now unreachable, HEAD and disk agree on C, and
    only the comparison against the first commitment can still see it."""
    root = _commitment_repo()
    saved = _point_hold_at(root)
    try:
        _quiet(_hold.cmd_commit)
        _git(root, "init", "-q")
        _git(root, "add", "records/held.manifest.json")
        _git(root, "commit", "-q", "-m", "first commitment")

        path = _os.path.join(root, "records", "held", _FAKE_FILE)
        man = _os.path.join(root, "records", "held.manifest.json")

        def rewrite(body):
            with _io.open(path, "w", encoding="utf-8") as fh:
                fh.write(body)
            with _io.open(man, encoding="utf-8") as fh:
                m = _json.load(fh)
            m["held"] = [_hold.entry(_FAKE_FILE)]
            with _io.open(man, "w", encoding="utf-8") as fh:
                _json.dump(m, fh, indent=2)

        rewrite('{"record_id": "%s", "verdict": "PASS"}' % _FAKE_ID)
        _git(root, "add", "records/held.manifest.json")
        _git(root, "commit", "-q", "-m", "visible tampering, hash B")

        rewrite('{"record_id": "%s", "verdict": "PASS", "extra": "x"}'
                % _FAKE_ID)
        _git(root, "add", "records/held.manifest.json")
        _git(root, "commit", "-q", "--amend", "-m", "amended, B is gone")

        log = _sub.check_output(["git", "log", "--oneline"], cwd=root,
                                text=True)
        return _quiet(_hold.cmd_verify), log.count("\n")
    except _sub.CalledProcessError as e:
        return "git fixture failed: %s" % e, None
    finally:
        (_hold.ROOT, _hold.RECORDS, _hold.HELD, _hold.MANIFEST,
         _hold.REGISTER) = saved
        _sh.rmtree(root, ignore_errors=True)

gate("commitment / a tampering commit amended away is still caught, "
     "against a real repository rather than a hand-built tuple",
     _amend_erasure_rc, (2, 2), "detect")

# ===== 10f-iii. cmd_audit(), the actual function hooks/pre-push invokes
#
# cmd_verify() and disclosure_scan() are both now tested as whole calls
# against real repositories. cmd_audit() is `disclosure_scan(...) or rc`,
# where rc is cmd_verify()'s result -- the one line that combines them into
# what --audit actually returns. Nothing had called cmd_audit() itself and
# checked that a disclosure leak is not lost when cmd_verify() is otherwise
# clean, which is the normal case: a repository with tidy commitments and a
# leak is not a contradiction, it is the exact situation this check exists
# to catch.

def _audit_rc(leak=False):
    """Only the manifest is added, the way a real repository is meant to be
    committed: held records themselves are never tracked. The first version
    of this fixture used `git add -A`, which tracked
    records/held/NBLX-...json along with the manifest, and disclosure_scan()
    correctly refused it -- the fixture was wrong, not the code, but it is
    worth naming: a test that accidentally recreates the exact defect the
    system exists to catch, and then reports the system as broken because
    the defect was caught, is a false negative shaped like a false positive."""
    root = _commitment_repo()
    saved = _point_hold_at(root)
    try:
        _quiet(_hold.cmd_commit)
        _git(root, "init", "-q")
        _git(root, "add", "records/held.manifest.json")
        _git(root, "commit", "-q", "-m", "first commitment")
        if leak:
            with _io.open(_os.path.join(root, "notes.md"), "w",
                          encoding="utf-8") as fh:
                fh.write("waiting on %s" % _FAKE_ID)
            _git(root, "add", "notes.md")
            _git(root, "commit", "-q", "-m", "a tracked file names it")
        return _quiet(_hold.cmd_audit)
    except _sub.CalledProcessError as e:
        return "git fixture failed: %s" % e
    finally:
        (_hold.ROOT, _hold.RECORDS, _hold.HELD, _hold.MANIFEST,
         _hold.REGISTER) = saved
        _sh.rmtree(root, ignore_errors=True)

gate("cmd_audit / clean commitments and no disclosure returns 0",
     lambda: _audit_rc(leak=False), 0, "quiet")

gate("cmd_audit / a disclosure leak is not lost when commitments are clean",
     lambda: _audit_rc(leak=True), 2, "detect")

# Pure, so they run whether or not git is installed.
gate("commitment / an unchanged hash is not reported as rewritten",
     lambda: _hold.rewritten_commitments(
         {"a.json": {"sha256": "x", "bytes": 1}},
         {"a.json": {"sha256": "x", "bytes": 1}}) == [],
     True, "quiet")

gate("commitment / a changed hash is reported with both sides",
     lambda: _hold.rewritten_commitments(
         {"a.json": {"sha256": "x", "bytes": 1}},
         {"a.json": {"sha256": "y", "bytes": 2}})
     == [("a.json", "x", "y", 1, 2)],
     True, "detect")

gate("commitment / a newly held record is not a rewritten commitment",
     lambda: _hold.rewritten_commitments(
         {}, {"new.json": {"sha256": "y", "bytes": 2}}) == [],
     True, "quiet")

gate("commitment / a manifest git cannot read is not read as agreement",
     lambda: _hold.rewritten_commitments(
         None, {"a.json": {"sha256": "y", "bytes": 2}}) == [],
     True, "quiet")

# ---- an entry HEAD has never seen
#
# commitments_not_in_head was written, documented, called from cmd_verify, and
# its answer assigned to a name nothing ever read. Every other comparison here
# iterates the HEAD side, so an entry HEAD does not carry was visited by
# nothing: rewritten_commitments reads head.items(), dropped_commitments
# subtracts disk from head. A record added to the manifest and not yet
# committed could therefore be rewritten without limit with no --amend asked
# for, and --verify printed "the manifest matches HEAD" every time.
#
# Reproduced against the file that had the hole: a second held record was
# added, --commit was run and the result deliberately not committed, and the
# record's verdict was flipped FAIL_UNSAFE -> PASS three times. --commit
# exited 0 on each, --verify exited 0 on each, and HEAD listed one file while
# --verify said two matched it.

def _add_a_second_record_and_recommit(root):
    """The attack, performed exactly as the docstring describes it.

    The second record is added after the first commitment is in history and
    the manifest naming it is deliberately never committed, which is the whole
    point: nothing in git carries a hash for it, so nothing can show it
    changing.
    """
    second = "NBLX-00000000-002.json"
    with _io.open(_os.path.join(root, "records", "held", second), "w",
                  encoding="utf-8") as fh:
        fh.write('{"record_id": "NBLX-00000000-002", "verdict": "PASS"}')
    _quiet(_hold.cmd_commit)

gate("commitment / a manifest entry HEAD does not carry is not a clean verify",
     lambda: _commitment_rc(_add_a_second_record_and_recommit), 2, "detect")

gate("commitment / the uncommitted entry is the one reported",
     lambda: _hold.commitments_not_in_head(
         {"a.json": {"sha256": "x"}},
         {"a.json": {"sha256": "x"}, "b.json": {"sha256": "y"}})
     == ["b.json"],
     True, "detect")

gate("commitment / an entry HEAD does carry is not called uncommitted",
     lambda: _hold.commitments_not_in_head(
         {"a.json": {"sha256": "x"}}, {"a.json": {"sha256": "x"}}) == [],
     True, "quiet")

gate("commitment / a manifest git cannot read is not a wall of accusations",
     lambda: _hold.commitments_not_in_head(
         None, {"a.json": {"sha256": "x"}}) == [],
     True, "quiet")

# ---- the original-commitment report was suppressed wholesale
#
# The suppression exists to stop one edit being printed twice under two
# headings. It was written as a cross product over both whole lists, so it
# asked whether the lists overlap anywhere rather than whether this row is a
# duplicate, and one shared filename silenced the block for every other file
# in it -- including the `return 2` that used to sit inside it. The exit code
# survived on `if rewritten:`, so the gate stayed red while naming the wrong
# file and printing no evidence for the right one.

_REW = [("a.json", "x", "X", 1, 2)]
_SINCE = [("a.json", "x", "X", 1, 2, "c0"), ("b.json", "y", "Y", 3, 4, "c1")]

gate("commitment / one overlapping file does not silence the whole report",
     lambda: [r[0] for r in _hold.unreported_since_first(_REW, _SINCE)]
     == ["b.json"],
     True, "detect")

gate("commitment / a file the HEAD check already named is not printed twice",
     lambda: _hold.unreported_since_first(
         _REW, [("a.json", "x", "X", 1, 2, "c0")]) == [],
     True, "quiet")

gate("commitment / with nothing reported against HEAD every row survives",
     lambda: [r[0] for r in _hold.unreported_since_first([], _SINCE)]
     == ["a.json", "b.json"],
     True, "detect")

# ================ 10f. what the disclosure scan can actually see in history
#
# The scan behind the public repository's push hook read only
# records/**.json, parsed each one, and matched a top-level record_id, while
# printing "no held record is reachable from any commit". A reply notice is a
# .md. A record committed somewhere other than records/ is not under
# records/. A record pasted into a write-up is neither, and that last shape is
# what put a docs/ folder on the public site. All three were a full
# disclosure of a record whose subject had not answered it, and all three
# walked past.

_REPLY_FILE = "right-of-reply-000.md"

def _leak_repo(files):
    """A repository that committed `files` and then deleted them.

    Deleting is the point. The working tree is clean afterwards and the
    commits still carry every byte, which is what a clone hands over.
    """
    root = _tmp.mkdtemp(prefix="nbx-leak-")
    _os.makedirs(_os.path.join(root, "records"))
    man = {"schema": "nobulex.held.manifest.v0", "held_count": 2,
           "held": [{"file": _FAKE_FILE, "bytes": 1, "sha256": "0" * 64,
                     "record_id": _FAKE_ID, "publication_status": "HELD"},
                    {"file": _REPLY_FILE, "bytes": 1, "sha256": "1" * 64}]}
    with _io.open(_os.path.join(root, "records", "held.manifest.json"), "w",
                  encoding="utf-8") as fh:
        _json.dump(man, fh, indent=2)
    _git(root, "init", "-q")
    for path, content in files.items():
        full = _os.path.join(root, path)
        d = _os.path.dirname(full)
        if d and not _os.path.isdir(d):
            _os.makedirs(d)
        with _io.open(full, "w", encoding="utf-8") as fh:
            fh.write(content)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "the commit that carries it")
    for path in files:
        _os.remove(_os.path.join(root, path))
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "gone from the working tree")
    return root

def _leaks(files):
    """What history_leaks finds, as sorted keys. Contents never come back."""
    root = _leak_repo(files)
    saved = _point_hold_at(root)
    try:
        found = _hold.history_leaks({_FAKE_ID},
                                    _hold.held_files_in_manifest())
        return sorted(found or {})
    except _sub.CalledProcessError as e:
        return ["git fixture failed: %s" % e]
    finally:
        (_hold.ROOT, _hold.RECORDS, _hold.HELD, _hold.MANIFEST,
         _hold.REGISTER) = saved
        _sh.rmtree(root, ignore_errors=True)

_RECORD_TEXT = _json.dumps({"record_id": _FAKE_ID, "verdict": "FAIL_UNSAFE",
                            "summary": "the finding, in full"})
_NOTICE_TEXT = "# Right of reply\n\nRecord %s concerns you.\n" % _FAKE_ID

gate("history / the record itself is found in a commit that deleted it",
     lambda: _leaks({"records/held/" + _FAKE_FILE: _RECORD_TEXT})
     == [_FAKE_FILE],
     True, "detect")

gate("history / the reply notice is found although it carries no record id",
     lambda: _leaks({"records/held/" + _REPLY_FILE: "no identifier in here"})
     == [_REPLY_FILE],
     True, "detect")

gate("history / a record committed outside records/ is found",
     lambda: _leaks({"docs/copy-of-a-record.json": _RECORD_TEXT})
     == [_FAKE_ID],
     True, "detect")

gate("history / a record pasted into a write-up is found",
     lambda: _leaks({"notes/audit.md": "we found:\n\n" + _RECORD_TEXT})
     == [_FAKE_ID],
     True, "detect")

gate("history / the notice found by name and the record by content, together",
     lambda: _leaks({"records/held/" + _REPLY_FILE: "no identifier",
                     "notes/audit.md": _RECORD_TEXT})
     == sorted([_REPLY_FILE, _FAKE_ID]),
     True, "detect")

gate("history / a repository carrying neither stays quiet",
     lambda: _leaks({"README.md": "nothing held is named here"}) == [],
     True, "quiet")

# The manifest is the one file where a held id belongs, labelled as a
# holding. If it counted as a leak the scan would refuse every push forever.
gate("history / the manifest naming the ids it commits to is not a leak",
     lambda: _leaks({"README.md": "clean"}) == [],
     True, "quiet")

# A commit message is published with its commit, and the scan read tracked
# files and history blobs and nothing else. "record: hold <id>" is the natural
# way to write the commit that issues a record.
def _message_leaks(message):
    root = _tmp.mkdtemp(prefix="nbx-msg-")
    try:
        _os.makedirs(_os.path.join(root, "records"))
        with _io.open(_os.path.join(root, "records", "held.manifest.json"),
                      "w", encoding="utf-8") as fh:
            _json.dump({"schema": "nobulex.held.manifest.v0", "held": []}, fh)
        _git(root, "init", "-q")
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", message)
        saved = _point_hold_at(root)
        try:
            return sorted(_hold.message_leaks({_FAKE_ID}) or {})
        finally:
            (_hold.ROOT, _hold.RECORDS, _hold.HELD, _hold.MANIFEST,
             _hold.REGISTER) = saved
    except _sub.CalledProcessError as e:
        return ["git fixture failed: %s" % e]
    finally:
        _sh.rmtree(root, ignore_errors=True)

gate("message / a commit message naming a held record is found",
     lambda: _message_leaks("record: hold %s pending reply" % _FAKE_ID)
     == [_FAKE_ID],
     True, "detect")

gate("message / the id in a message body, not the subject line, is found",
     lambda: _message_leaks("record: hold one\n\nThe record is %s.\n"
                            % _FAKE_ID) == [_FAKE_ID],
     True, "detect")

gate("message / a message naming no record stays quiet",
     lambda: _message_leaks("suite: widen the disclosure scan") == [],
     True, "quiet")

gate("message / nothing held means nothing to look for",
     lambda: _hold.message_leaks(set()) == {},
     True, "quiet")

# ---- the three disclosure scans compared ids exactly
#
# disclosure_scan asked `i in text`, message_leaks asked `rid in body` and
# history_leaks asked `rid in blob`. All three are the last gate before a
# public push, and all three missed a held id spelled in lower case.
#
# render_register.leaked() had already been fixed for exactly this, and its
# docstring states the rule the fix came from: two guards that compare the
# same way are one guard. Three scans comparing the same wrong way are one
# scan. render_register._canon_id records that a lower-case spelling of a held
# id has already occurred in this repository, so this is not a hypothetical
# spelling; it is the spelling that got past the previous guard.
#
# Reproduced against the file that had it: a held id in lower case, in a
# tracked file AND in a commit message, passed the export gate clean at rc=0,
# while the same id in upper case exited 2.

# Called inside each thunk rather than bound at module level, for the reason
# gate()'s own docstring gives: a name this file resolves before it exists
# takes the whole run down at that line and every case after it goes unrun.
def _canon():
    return _hold.canon_ids({_FAKE_ID})

gate("disclosure / a held id in lower case is found",
     lambda: _hold.ids_in("waiting on %s, adverse" % _FAKE_ID.lower(),
                          _canon()) == [_FAKE_ID],
     True, "detect")

gate("disclosure / a held id in mixed case is found",
     lambda: _hold.ids_in("see Nblx-00000000-000 for the finding", _canon())
     == [_FAKE_ID],
     True, "detect")

gate("disclosure / the exact spelling is still found",
     lambda: _hold.ids_in("waiting on %s" % _FAKE_ID, _canon()) == [_FAKE_ID],
     True, "detect")

gate("disclosure / the id is reported in the manifest's spelling, not the "
     "spelling found",
     lambda: _hold.ids_in(_FAKE_ID.lower(), _canon())[0] == _FAKE_ID,
     True, "detect")

gate("disclosure / a manifest id with whitespace around it still matches",
     lambda: _hold.ids_in("waiting on %s" % _FAKE_ID,
                          _hold.canon_ids({" %s " % _FAKE_ID})) != [],
     True, "detect")

gate("disclosure / text naming no held record stays quiet",
     lambda: _hold.ids_in("suite: widen the disclosure scan", _canon()) == [],
     True, "quiet")

gate("disclosure / a different id is not folded into this one",
     lambda: _hold.ids_in("NBLX-00000000-001", _canon()) == [],
     True, "quiet")

gate("disclosure / nothing to search for matches nothing rather than "
     "everything",
     lambda: _hold.ids_in("any text at all", _hold.canon_ids(set())) == [],
     True, "quiet")

gate("disclosure / a non-string id contributes no empty needle",
     lambda: _hold.canon_ids({None, "", "  "}) == [],
     True, "quiet")

gate("message / a commit message naming a held record in lower case is found",
     lambda: _message_leaks("record: hold %s pending reply"
                            % _FAKE_ID.lower()) == [_FAKE_ID],
     True, "detect")

# ===== 10f-ii. disclosure_scan(), the call the push hook actually makes
#
# Tracked files, git history and commit messages are each tested above by
# calling the function that scans that one thing. hooks/pre-push never calls
# any of them: it runs `hold.py --audit`, which dispatches to cmd_audit(),
# which calls disclosure_scan(held_ids_on_disk()) once, combining all three.
# Nothing here had called disclosure_scan() itself before this, on a real
# repository, and confirmed the three results actually reach the one
# returned rc rather than one masking another on the way out.

def _disclosure_repo(tracked=None, buried=None, message=None):
    """held.manifest.json for one record, plus whatever `files` describe.

    tracked: written, committed, and left in the working tree -- a live leak
    a plain `git ls-files` scan would see.
    buried: committed, then deleted in a second commit -- gone from the tree,
    still in every clone's history.
    message: the final commit's message.
    """
    root = _tmp.mkdtemp(prefix="nbx-disc-")
    _os.makedirs(_os.path.join(root, "records"))
    man = {"schema": "nobulex.held.manifest.v0", "held_count": 1,
           "held": [{"file": _FAKE_FILE, "bytes": 1, "sha256": "0" * 64,
                     "record_id": _FAKE_ID, "publication_status": "HELD"}]}
    with _io.open(_os.path.join(root, "records", "held.manifest.json"), "w",
                  encoding="utf-8") as fh:
        _json.dump(man, fh)
    _git(root, "init", "-q")
    for path, content in (buried or {}).items():
        full = _os.path.join(root, path)
        d = _os.path.dirname(full)
        if d and not _os.path.isdir(d):
            _os.makedirs(d)
        with _io.open(full, "w", encoding="utf-8") as fh:
            fh.write(content)
    if buried:
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "carries it")
        for path in buried:
            _os.remove(_os.path.join(root, path))
    for path, content in (tracked or {}).items():
        full = _os.path.join(root, path)
        d = _os.path.dirname(full)
        if d and not _os.path.isdir(d):
            _os.makedirs(d)
        with _io.open(full, "w", encoding="utf-8") as fh:
            fh.write(content)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", message or "nothing notable", "--allow-empty")
    return root

def _disclosure(**kwargs):
    root = _disclosure_repo(**kwargs)
    saved = _point_hold_at(root)
    try:
        return _hold.disclosure_scan({_FAKE_ID})
    except _sub.CalledProcessError as e:
        return "git fixture failed: %s" % e
    finally:
        (_hold.ROOT, _hold.RECORDS, _hold.HELD, _hold.MANIFEST,
         _hold.REGISTER) = saved
        _sh.rmtree(root, ignore_errors=True)

gate("disclosure_scan / a leak in a tracked file alone is caught",
     lambda: _disclosure(tracked={"notes/audit.md": _RECORD_TEXT}), 2, "detect")

gate("disclosure_scan / a leak only in history is caught, with nothing "
     "tracked to find it by",
     lambda: _disclosure(buried={"notes/old.md": _RECORD_TEXT}), 2, "detect")

gate("disclosure_scan / a leak only in a commit message is caught",
     lambda: _disclosure(
         message="record: hold %s pending reply" % _FAKE_ID), 2, "detect")

gate("disclosure_scan / all three at once still resolves to one refusal",
     lambda: _disclosure(tracked={"notes/audit.md": _RECORD_TEXT},
                         buried={"notes/old.md": _RECORD_TEXT},
                         message="record: hold %s pending reply" % _FAKE_ID),
     2, "detect")

gate("disclosure_scan / nothing leaked anywhere returns clean",
     lambda: _disclosure(tracked={"README.md": "clean"}), 0, "quiet")

# ============ 10g. why P04 through P08 have nothing to read
#
# Those five probes all grade one shared live response. When it was unusable
# the runner swallowed the failure whole -- `except Exception: pass`, the
# isError flag dropped, parse_bars' own note discarded -- and each probe
# reported "no bars", which says the subject returned nothing. It may have
# refused, or the call may have raised inside the harness, which is not a fact
# about the subject at all. The runner already gets this right for authority
# A1 through a1_missing(); these assert it for the subject.

import run as _run

# Named for what it wraps rather than _note, which is taken. The page-note
# fixture up in section 10c is called _note, and this file is one module, so
# the second definition replaced the first from this line to the end. It was
# safe only by accident of ordering: gate() calls its thunk immediately, so
# every case that wanted the page note had already run. A case added below
# this line would have called this function instead, with the wrong arguments
# at best and a quietly wrong answer at worst, and nothing would have said so.
def _pull_note(**kw):
    kw.setdefault("text", None)
    kw.setdefault("is_error", False)
    kw.setdefault("bars", [{"Open": 1}])
    kw.setdefault("parse_note", None)
    return _run.live_pull_note(kw["text"], kw["is_error"], kw["bars"],
                               kw["parse_note"], kw.get("raised"))

gate("live / a readable record array leaves the five probes to their work",
     lambda: _pull_note() is None, True, "quiet")

gate("live / a call that raised is reported as a fact about the run",
     lambda: "raised inside the harness" in (_pull_note(raised="TimeoutError: x") or ""),
     True, "detect")

gate("live / a call that raised does not read as the subject returning nothing",
     lambda: "not about the subject" in (_pull_note(raised="TimeoutError: x") or ""),
     True, "detect")

gate("live / a protocol refusal is named as a refusal",
     lambda: "refused" in (_pull_note(is_error=True, bars=None) or ""),
     True, "detect")

gate("live / a payload that is not a record array says which",
     lambda: "payload is not JSON" in (
         _pull_note(bars=None, parse_note="payload is not JSON") or ""),
     True, "detect")

gate("live / an empty record array is distinguished from an unreadable one",
     lambda: (_pull_note(bars=[]) or "") != (_pull_note(bars=None) or "")
     and "empty record array" in (_pull_note(bars=[]) or ""),
     True, "detect")

# Order matters: a refusal that also failed to parse is a refusal first,
# because that is the fact about the subject.
gate("live / a refusal that also fails to parse reads as the refusal",
     lambda: "refused" in (
         _pull_note(is_error=True, bars=None, parse_note="payload is not JSON") or ""),
     True, "detect")

# ================= 10e. the subject tuple names the subject, not the folder
# run.py used os.path.basename(subject_dir) as the package name. That is the
# operator's choice of clone path, so the same commit cloned into ~/tmp
# produced a record whose package was "tmp", and the renderer's held-subject
# guard then had "tmp" to search for. The origin covered that case, so it was
# never a leak; the record simply named the wrong thing, and the record is the
# evidence.

import run as _run

# Reached through getattr so that a build without these functions reports five
# failed cases instead of taking the whole suite down with an AttributeError.
# A self-test that crashes tells you less than one that goes red.
_pkg = getattr(_run, "package_name", lambda *_a: None)
_repo = getattr(_run, "repo_from_origin", lambda *_a: object())

gate("subject / a tmp clone is still named by its origin",
     lambda: _pkg("/somewhere/tmp",
                       "https://github.com/acme/acme-mcp.git") == "acme-mcp",
     True, "detect")

gate("subject / an ssh remote parses the same as an https one",
     lambda: _repo("git@github.com:acme/acme-mcp.git") == "acme-mcp",
     True, "detect")

gate("subject / a remote with no .git suffix still parses",
     lambda: _repo("https://github.com/acme/acme-mcp") == "acme-mcp",
     True, "detect")

gate("subject / no remote falls back to the directory name",
     lambda: _pkg("/somewhere/acme-mcp", None) == "acme-mcp",
     True, "quiet")

gate("subject / a string that is not a remote is not treated as one",
     lambda: _repo("not a url") is None,
     True, "quiet")

# ==================== 10f. fidelity payloads that used to be called clean
# Same shape as the ohlc cases above, one probe over. A bar the comparison
# could not use is not a bar that agreed.

_fdays = ["2026-07-2%d" % i for i in range(1, 6)]
_fsub = [bar(d, 100.0, 100.0, 100.0, 100.0) for d in _fdays]

check("fidelity / an authority close of zero everywhere is not a pass",
      classify_fidelity(_fsub,
                        auth_bars([(d, 0.0) for d in _fdays]), TOL),
      INDETERMINATE, None, "quiet")

_fmixed = [dict(b) for b in _fsub]
for _b in _fmixed[:3]:
    _b["Close"] = str(_b["Close"])
check("fidelity / dropping unreadable closes must not improve the overlap",
      classify_fidelity(_fmixed,
                        auth_bars([(d, 100.0) for d in _fdays]), TOL),
      INDETERMINATE, None, "quiet")

check("fidelity / a fully readable matching payload still passes",
      classify_fidelity(_fsub, auth_bars([(d, 100.0) for d in _fdays]), TOL),
      PASS, None, "quiet")

# ========= 10f-2. the same hole on the AUTHORITY side of the comparison
# The overlap floor above was corrected on the subject side only. `auth` is the
# post-_numeric FILTERED dict, so an authority bar whose close arrived
# unreadable -- close:null over a holiday, a nan off the wire -- shrank the
# DENOMINATOR, and the floor was then satisfied by whatever few sessions
# survived. auth_unreadable was consulted only under `if auth_unreadable and
# not auth`, i.e. only when ALL of them were unreadable, so every partial hole
# passed through in silence.
#
# This is the worst shape in the file, because it is a published PASS over
# transport corruption: the subject is 99% wrong on eight of ten sessions and
# the authority carries close:null on those same eight. The evidence string
# read "2 overlapping sessions compared, worst deviation 0.00000% within
# tolerance" and never mentioned the eight it could not read. The same subject
# against a readable authority is FAIL_UNSAFE at 99.0909%.
_ahd = ["2026-01-%02d" % d for d in range(1, 11)]
_asub_ok = [bar(d, 100.0, 100.0, 100.0, 100.0 + i)
            for i, d in enumerate(_ahd)]
_asub_bad = [bar(d, 100.0, 100.0, 100.0, (100.0 + i) if i < 2 else 1.0)
             for i, d in enumerate(_ahd)]
_aauth_full = auth_bars([(d, 100.0 + i) for i, d in enumerate(_ahd)])
_aauth_holed = [{"date": d, "ts": None, "open": None, "high": None,
                 "low": None, "close": (100.0 + i) if i < 2 else None}
                for i, d in enumerate(_ahd)]
_aauth_one = [{"date": d, "ts": None, "open": None, "high": None,
               "low": None, "close": None if i == 4 else 100.0 + i}
              for i, d in enumerate(_ahd)]

check("fidelity / an authority hole must not publish a PASS over corruption",
      classify_fidelity(_asub_bad, _aauth_holed, TOL),
      INDETERMINATE, None, "detect")

check("fidelity / a clean subject is not cleared by an authority it could not read",
      classify_fidelity(_asub_ok, _aauth_holed, TOL),
      INDETERMINATE, None, "detect")

# One unreadable authority close. The subject side already returns
# INDETERMINATE for exactly one unreadable bar out of ten; the authority side
# returned PASS, and a comparison is only as readable as its weaker half.
check("fidelity / one unreadable authority close is disclosed, not dropped",
      classify_fidelity(_asub_ok, _aauth_one, TOL),
      INDETERMINATE, None, "detect")

_results.append((classify_fidelity(_asub_ok, _aauth_one, TOL)[0]
                 == classify_fidelity(
                     [dict(b, Close=str(b["Close"])) if i == 4 else b
                      for i, b in enumerate(_asub_ok)], _aauth_full, TOL)[0],
                 "detect",
                 "fidelity / one unreadable bar grades the same on either side",
                 classify_fidelity(_asub_ok, _aauth_one, TOL)[0], None,
                 INDETERMINATE, None,
                 "the denominator is what each side sent, not what survived parsing"))

# must not fire: the corruption still has to be catchable, and an agreeing
# readable pair still has to pass.
check("fidelity / a readable authority still catches the same corruption",
      classify_fidelity(_asub_bad, _aauth_full, TOL),
      FAIL_UNSAFE, "stale_value", "detect")

check("fidelity / ten readable agreeing sessions still pass",
      classify_fidelity(_asub_ok, _aauth_full, TOL),
      PASS, None, "quiet")

# ============== 10g. window_span inputs that crashed or overstated
# Two of these raised out of the classifier. A classifier that raises does not
# just lose its own verdict: run.py's boundary turns the whole run into a
# failed one and every other probe's result goes with it.

_wsiso = json.dumps([{"Date": "2026-%02d-01" % m, "Close": 1} for m in range(1, 10)])
_wsp, _ = parse_bars(_wsiso)

_wsbad = json.dumps([{"Date": "01/05/2026", "Close": 1},
                     {"Date": "12/31/2026", "Close": 1}])
_wsbadp, _ = parse_bars(_wsbad)
check("window_span / non-ISO dates are refused, not fed to strptime",
      safe(classify_window_span, _wsbad, False, _wsbadp, 365, "period='1y'"),
      INDETERMINATE, None, "quiet")

check("window_span / a zero-length request is not a window to fall short of",
      safe(classify_window_span, _wsiso, False, _wsp, 0, "period='0d'"),
      INDETERMINATE, None, "quiet")

check("window_span / a real request over ISO dates still passes",
      classify_window_span(_wsiso, False, _wsp, 200, "period='1y'"),
      PASS, None, "quiet")

# ============ 10h. the authority reader, on its upstream's ordinary answers
# These three used to raise TypeError, KeyError and IndexError. run.py catches
# broadly so the run survived, but the record then said the authority was
# unreachable, with a Python type name where the upstream's own message
# belonged. The authority was reached and did answer.

import harness as _h

def _a1_with(payload):
    real = _h._get_json
    _h._get_json = lambda *a, **k: payload
    try:
        _h.a1_chart("AAPL")
        return None
    except _h.AuthorityUnavailable as e:
        return e.as_dict()
    except Exception as e:
        return {"reason": "%s: %s" % (type(e).__name__, e), "unstructured": True}
    finally:
        _h._get_json = real

_delisted = _a1_with({"chart": {"result": None, "error": {
    "code": "Not Found", "description": "No data found, symbol may be delisted"}}})
gate("authority / a delisted symbol is reported in the upstream's own words",
     lambda: bool(_delisted) and "delisted" in (_delisted.get("reason") or "")
     and not _delisted.get("unstructured"),
     True, "detect")

_nots = _a1_with({"chart": {"result": [{"meta": {}, "indicators": {"quote": [{}]}}]}})
gate("authority / a result with no timestamps is a stated answer, not a crash",
     lambda: bool(_nots) and not _nots.get("unstructured"),
     True, "detect")

_ragged = _a1_with({"chart": {"result": [{"meta": {"gmtoffset": 0},
    "timestamp": [1, 2, 3],
    "indicators": {"quote": [{"open": [1], "high": [1], "low": [1], "close": [1]}]}}]}})
gate("authority / a ragged read is refused rather than truncated",
     lambda: bool(_ragged) and not _ragged.get("unstructured"),
     True, "detect")

_ok = _a1_with({"chart": {"result": [{"meta": {"symbol": "AAPL", "gmtoffset": -14400},
    "timestamp": [1750000000],
    "indicators": {"quote": [{"open": [1.0], "high": [2.0], "low": [0.5], "close": [1.5]}]}}]}})
gate("authority / a well-formed response still reads clean",
     lambda: _ok is None, True, "quiet")

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


# ===================================== the spent-id guard, on prefix collisions
# The guard that refuses a record id already on disk matched with startswith,
# so NBLX-<day>-100 collided with NBLX-<day>-1000 because one id is a prefix
# of the other. Safe in direction, it stops a run rather than destroying a
# record, but it stops the wrong run and reports the wrong id as spent. Latent
# until the thousandth record, and cheaper to fix than to remember.
#
# These four cases used to run against a copy of the rule pasted into this
# file, because the rule was inline in run.py's main() and nothing else could
# reach it. So they were green whatever run.py did: the copy could not drift
# and the original could, which is the same defect this suite grades others
# for, a check that reports on something other than the thing it names. The
# rule is run.py:spends_record_id() now and these call it, the way
# OUTCOME_ORDER is held to harness._ORDER rather than to a second list.

def _spent(files, rid):
    """run.py's own matching rule, asked of a list of filenames."""
    return any(_run.spends_record_id(f, rid) for f in files)

_ON_DISK = ["NBLX-00000000-1000.json", "NBLX-00000000-002.json",
            "NBLX-00000000-003.withdrawn.json"]

check("spent id / a shorter id is not spent by a longer one that starts the same",
      (_spent(_ON_DISK, "NBLX-00000000-100"), None, None),
      False, None, "detect")

check("spent id / an exact match is still spent",
      (_spent(_ON_DISK, "NBLX-00000000-1000"), None, None),
      True, None, "quiet")

check("spent id / a withdrawn record still spent its number",
      (_spent(_ON_DISK, "NBLX-00000000-003"), None, None),
      True, None, "quiet")

check("spent id / an unused number is free",
      (_spent(_ON_DISK, "NBLX-00000000-999"), None, None),
      False, None, "quiet")

# ================================================ record id sequencing
# The number on a record is its identity, and other documents cite it. Two
# records wearing one number is the same defect this suite grades others for:
# the citation still resolves, so nothing looks broken, and it points at the
# wrong thing. These cases are cheap and the failure they prevent is not.

def _seq(name, names, day, want, kind):
    got = next_in_sequence(names, day)
    _results.append((got == want, kind, name, got, None, want, None,
                     f"from {names!r}"))

_seq("an empty register starts at 001",
     [], "19990103", "NBLX-19990103-001", "quiet")

_seq("files that are not records consume no numbers",
     ["held.manifest.json", "README.md", ".DS_Store", "notes-002.txt"],
     "19990103", "NBLX-19990103-001", "quiet")

_seq("the sequence is global and does not restart on a new day",
     ["NBLX-19990101-001.json", "NBLX-19990102-002.json",
      "NBLX-19990102-003.json"],
     "19990103", "NBLX-19990103-004", "detect")

_seq("a withdrawn record keeps its number and is not reissued",
     ["NBLX-19990101-001.withdrawn.json"],
     "19990103", "NBLX-19990103-002", "detect")

_seq("the number is zero padded past single digits",
     ["NBLX-19990101-009.json"], "19990103", "NBLX-19990103-010", "detect")

_seq("gaps do not lower the next number",
     ["NBLX-19990101-001.json", "NBLX-19990101-007.json"],
     "19990103", "NBLX-19990103-008", "detect")


# ---------------------------------------------------------------- 11. the gate
# Publication is the only irreversible act here, so the command that performs
# it gets planted failures rather than a walkthrough. Each case below builds a
# record in a throwaway tree, asks hold.py to clear it, and checks the answer.
#
# The must-not-fire half matters as much as the detect half. A gate that
# refuses everything is not a gate, it is a wall, and it would have shipped
# looking correct: the register was empty either way, so "nothing published"
# could not tell a working gate from a stuck one. That is how the defect this
# section exists for survived. run.py wrote PUBLISHABLE, render_register.py
# published only CLEARED or PUBLISHED, no command turned one into the other,
# and the register was structurally unable to ever carry a record no matter
# how many subjects passed.
from datetime import timedelta as _td

def _clear_fixture(root, rid, pub, withdrawn=False):
    _os.makedirs(_os.path.join(root, "records", "held"), exist_ok=True)
    held = pub.get("status") == "HELD"
    d = (_os.path.join(root, "records", "held") if held
         else _os.path.join(root, "records"))
    rec = {"schema": "record-v0.4", "record_id": rid,
           "verdict": "FAIL_UNSAFE" if held else "PASS",
           "publication": pub,
           "validity": {"from": None, "until": None}}
    if withdrawn:
        rec["status"] = "WITHDRAWN"
    with _io.open(_os.path.join(d, rid + ".json"), "w", encoding="utf-8") as fh:
        _json.dump(rec, fh)

def _try_clear(rid, pub, withdrawn=False):
    root = _tmp.mkdtemp(prefix="nblx-clear-")
    saved = _point_hold_at(root)
    try:
        _clear_fixture(root, rid, pub, withdrawn)
        return _quiet(_hold.cmd_clear, rid)
    finally:
        (_hold.ROOT, _hold.RECORDS, _hold.HELD, _hold.MANIFEST,
         _hold.REGISTER) = saved
        _sh.rmtree(root, ignore_errors=True)

def _gate(name, rid, pub, want_rc, kind, withdrawn=False):
    got = _try_clear(rid, pub, withdrawn)
    _results.append((got == want_rc, kind, name, got, None, want_rc, None,
                     "status=%r" % (pub.get("status"),)))

def _ror(**kw):
    return dict({"required": True, "artifact_delivered_at": None,
                 "window_closes_at": None, "reply_received_at": None}, **kw)

_now = datetime.now(timezone.utc)
_past = (_now - _td(days=2)).isoformat()
_future = (_now + _td(days=5)).isoformat()
_long_ago = (_now - _td(days=9)).isoformat()

_gate("an adverse record nobody delivered does not clear",
      "NBLX-19990101-001",
      {"status": "HELD", "held_by": "right_of_reply", "right_of_reply": _ror()},
      1, "detect")

_gate("an adverse record whose reply window is still open does not clear",
      "NBLX-19990101-002",
      {"status": "HELD", "held_by": "right_of_reply",
       "right_of_reply": _ror(artifact_delivered_at=_past,
                              window_closes_at=_future)},
      1, "detect")

_gate("a delivered record with no stated deadline does not clear",
      "NBLX-19990101-003",
      {"status": "HELD", "held_by": "right_of_reply",
       "right_of_reply": _ror(artifact_delivered_at=_past)},
      1, "detect")

_gate("a withdrawn record does not come back by clearing it",
      "NBLX-19990101-004",
      {"status": "HELD", "held_by": "right_of_reply",
       "right_of_reply": _ror(artifact_delivered_at=_long_ago,
                              window_closes_at=_past)},
      1, "detect", withdrawn=True)

_gate("clearing something already cleared is refused, not repeated",
      "NBLX-19990101-005", {"status": "CLEARED"}, 1, "detect")

_gate("a non-adverse record clears",
      "NBLX-19990101-006",
      {"status": "PUBLISHABLE", "held_by": None, "right_of_reply": None},
      0, "quiet")

_gate("an adverse record past a closed window clears",
      "NBLX-19990101-007",
      {"status": "HELD", "held_by": "right_of_reply",
       "right_of_reply": _ror(artifact_delivered_at=_long_ago,
                              window_closes_at=_past)},
      0, "quiet")

# The point of the whole section. Without this the cases above could all pass
# while the gate still opened onto a wall, which is exactly what shipped.
def _cleared_record_reaches_the_register():
    root = _tmp.mkdtemp(prefix="nblx-clear-")
    saved = _point_hold_at(root)
    try:
        _clear_fixture(root, "NBLX-19990101-008",
                       {"status": "PUBLISHABLE", "held_by": None,
                        "right_of_reply": None})
        _quiet(_hold.cmd_clear, "NBLX-19990101-008")
        with _io.open(_os.path.join(root, "records",
                                    "NBLX-19990101-008.json"),
                      encoding="utf-8") as fh:
            return _rr.is_held(_json.load(fh))
    finally:
        (_hold.ROOT, _hold.RECORDS, _hold.HELD, _hold.MANIFEST,
         _hold.REGISTER) = saved
        _sh.rmtree(root, ignore_errors=True)

_after_clearing = _cleared_record_reaches_the_register()
_results.append((_after_clearing is False, "quiet",
                 "a cleared record is one the renderer will publish",
                 _after_clearing, None, False, None,
                 "render_register.is_held() must be False after clearing"))


# ------------------------------------------------------- 12. the transport
# Everything above this point tests pure functions on payloads that were typed
# into this file. That is most of the suite and it is not the whole risk. The
# payloads have to arrive first, and they arrive through MCPStdio: a subprocess,
# a pipe, a select loop, and a hand-rolled JSON-RPC framing that exists so this
# harness cannot inherit a bug from the same library family as its subjects.
#
# Nothing tested it. A classifier that reads a payload correctly is no use if
# the transport handed it the wrong payload, mislabelled a live subject as
# dead, or discarded the subject's own account of why it died. Each case below
# starts a real process and plants a real transport failure.

_PY = sys.executable

def _stub(body, timeout=8):
    """A subject that behaves exactly as badly as the case requires."""
    return _h.MCPStdio([_PY, "-u", "-c", body], cwd=".", timeout=timeout)

def _transport(name, fn, want, kind):
    try:
        got = fn()
    except Exception as e:
        got = type(e).__name__
    _results.append((got == want, kind, name, got, None, want, None, ""))

# A server that prints a banner before speaking JSON-RPC is common and is not
# fatal, but the banner is evidence: it means the channel reserved for framing
# carried something else. Dropping it silently would erase the only trace.
def _noise_is_kept():
    c = _stub("import sys,json\n"
              "sys.stdout.write('Server v1.0 starting\\n')\n"
              "line=sys.stdin.readline()\n"
              "req=json.loads(line)\n"
              "print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':{}}))\n")
    try:
        c.request("initialize", {})
        return c.protocol_noise
    finally:
        c.close()

_transport("a banner on the JSON-RPC channel is recorded, not discarded",
           _noise_is_kept, ["Server v1.0 starting"], "detect")

# The id is the only thing tying a response to its request. A client that
# returns the first message it sees will hand a probe the answer to a
# different question, and every classifier downstream will read it as truth.
def _wrong_id_is_not_accepted():
    c = _stub("import sys,json\n"
              "line=sys.stdin.readline()\n"
              "req=json.loads(line)\n"
              "print(json.dumps({'jsonrpc':'2.0','id':999,'result':{'wrong':1}}))\n"
              "print(json.dumps({'jsonrpc':'2.0','id':req['id'],"
              "'result':{'right':1}}))\n")
    try:
        return c.request("initialize", {}).get("result")
    finally:
        c.close()

_transport("a response carrying another request's id is not mistaken for this one",
           _wrong_id_is_not_accepted, {"right": 1}, "detect")

# A subject that dies at import answers nothing. If that surfaced as anything
# other than an explicit end-of-stream, the runner could not tell "died" from
# "said something unexpected", and P10 grades those differently.
def _dead_subject_is_eof():
    c = _stub("import sys; sys.exit(1)")
    try:
        c.request("initialize", {})
        return "returned normally"
    except EOFError:
        return "EOFError"
    finally:
        c.close()

_transport("a subject that exits at import raises end of stream",
           _dead_subject_is_eof, "EOFError", "detect")

# A subject that accepts the connection and then never answers is the case
# that hangs a harness forever. The deadline is what makes the suite finish.
def _silent_subject_times_out():
    c = _stub("import time; time.sleep(30)", timeout=1)
    try:
        c.request("initialize", {})
        return "returned normally"
    except TimeoutError:
        return "TimeoutError"
    finally:
        c.close()

_transport("a subject that accepts and never answers hits the deadline",
           _silent_subject_times_out, "TimeoutError", "detect")

# close() runs twice by design: once when startup fails, so the subject's own
# diagnosis reaches the probe, and again in the runner's finally block. The
# second read of a drained pipe returns nothing, and letting that nothing
# overwrite the captured stderr would discard the only evidence there is.
def _close_is_idempotent():
    c = _stub("import sys; sys.stderr.write('ModuleNotFoundError: pandas\\n'); "
              "sys.exit(1)")
    first = c.close()
    second = c.close()
    return (first.strip(), second.strip())

_transport("closing twice does not erase what the subject said on its way out",
           _close_is_idempotent,
           ("ModuleNotFoundError: pandas", "ModuleNotFoundError: pandas"),
           "detect")

# exit_summary is the sentence that goes in the record. "exited 0" and
# "exited 0 having said nothing at all" are different observations about how
# much the subject accounted for itself, and the record keeps them apart.
def _summary(body):
    c = _stub(body)
    c.close()
    return c.exit_summary()

_transport("a silent clean exit is described as giving no account of itself",
           lambda: _summary("import sys; sys.exit(0)"),
           "exited 0 and wrote nothing to stderr, so it gave no account of "
           "itself", "detect")

_transport("a clean exit that wrote to stderr is not described as silent",
           lambda: _summary("import sys; sys.stderr.write('warn\\n'); "
                            "sys.exit(0)"),
           "exited 0 with output on stderr", "detect")

_transport("a nonzero exit reports its code",
           lambda: _summary("import sys; sys.exit(3)"), "exited 3", "detect")

# call() is what every probe actually invokes. Its contract is a three-tuple,
# and the two failure shapes it has to keep apart are a JSON-RPC error, which
# means the call did not happen, and isError on a result, which means it did
# happen and went wrong. Collapsing those loses the distinction between a tool
# that refused and a tool that failed.
def _call(body):
    c = _stub(body)
    try:
        c._id = 0
        return c.call("t", {})
    finally:
        c.close()

# Two ways a subject flips a finding into a pass through the flag channel,
# both reproduced against real subprocesses.
#
# `"error" in r` tested key presence, not truth. JSON-RPC says error must be
# absent on success, but "error": null beside a valid result is what a struct
# without omitempty serializes to. A subject fabricating bars for a ticker
# that does not exist was graded PASS, "refused through the protocol error
# channel", and the body was discarded so the record kept no evidence either.
_transport("a null error field beside a result is not a refusal",
           lambda: _call("import sys,json\n"
                         "req=json.loads(sys.stdin.readline())\n"
                         "print(json.dumps({'jsonrpc':'2.0','id':req['id'],"
                         "'error':None,'result':{'content':"
                         "[{'type':'text','text':'FABRICATED'}],"
                         "'isError':False}}))\n")[:2],
           ("FABRICATED", False), "detect")

# bool("false") is True, and so is bool("0") and bool("no").
_transport("the string false is not a true error flag",
           lambda: _call("import sys,json\n"
                         "req=json.loads(sys.stdin.readline())\n"
                         "print(json.dumps({'jsonrpc':'2.0','id':req['id'],"
                         "'result':{'content':"
                         "[{'type':'text','text':'FABRICATED'}],"
                         "'isError':'false'}}))\n")[:2],
           ("FABRICATED", False), "detect")

_transport("text content is joined out of the result",
           lambda: _call("import sys,json\n"
                         "req=json.loads(sys.stdin.readline())\n"
                         "print(json.dumps({'jsonrpc':'2.0','id':req['id'],"
                         "'result':{'content':[{'type':'text','text':'a'},"
                         "{'type':'text','text':'b'}]}}))\n")[0],
           "a\nb", "quiet")

_transport("a JSON-RPC error is reported as an error and carries no text",
           lambda: _call("import sys,json\n"
                         "req=json.loads(sys.stdin.readline())\n"
                         "print(json.dumps({'jsonrpc':'2.0','id':req['id'],"
                         "'error':{'code':-32601,'message':'no such tool'}}))\n"
                         )[:2],
           (None, True), "detect")

_transport("isError on a result is an error even though the call completed",
           lambda: _call("import sys,json\n"
                         "req=json.loads(sys.stdin.readline())\n"
                         "print(json.dumps({'jsonrpc':'2.0','id':req['id'],"
                         "'result':{'isError':True,'content':"
                         "[{'type':'text','text':'boom'}]}}))\n")[:2],
           ("boom", True), "detect")


# ================= interpreter preflight before any observation
# A bad local interpreter is operator configuration, not subject behavior.
# Stop at git if preflight lets it through, so these checks never reach a
# live authority or launch a subject, including against the old runner.
import tempfile

def _invalid_interpreter_refused(kind):
    import contextlib
    import io
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as tmp:
        candidate = os.path.join(tmp, "python")
        if kind == "directory":
            os.mkdir(candidate)
        elif kind == "nonexecutable":
            with open(candidate, "w") as f:
                f.write("not executable\n")
            os.chmod(candidate, 0o600)
        err = io.StringIO()
        argv = ["run.py", "--subject-dir", tmp, "--python", candidate,
                "--upstream", "fictional fixture", "--out", tmp]
        with patch.object(sys, "argv", argv), contextlib.redirect_stderr(err), \
                patch.object(_run, "git", side_effect=AssertionError(
                    "invalid interpreter reached subject inspection")):
            rc = _run.main()
        return rc == 2 and "interpreter" in err.getvalue() and \
            "no probes ran" in err.getvalue() and not any(
                name.endswith(".json") for name in os.listdir(tmp))

for _kind in ("missing", "directory", "nonexecutable"):
    gate(f"interpreter / {_kind} is refused before observing a subject",
         lambda k=_kind: _invalid_interpreter_refused(k), True, "detect")

def _interpreter_control(relative):
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as tmp:
        candidate = os.path.join(tmp, "fixture-python")
        os.symlink(sys.executable, candidate)
        if relative:
            supplied = os.path.relpath(candidate)
            resolved = _run.resolve_subject_python(supplied)
        else:
            with patch.dict(os.environ, {"PATH": tmp}):
                resolved = _run.resolve_subject_python("fixture-python")
        result = subprocess.run([resolved, "-c", "print('interpreter-ok')"],
                                cwd=tmp, capture_output=True, text=True,
                                timeout=10)
        return resolved == candidate and result.returncode == 0 and \
            result.stdout.strip() == "interpreter-ok"

gate("interpreter / PATH command works after changing subject directory",
     lambda: _interpreter_control(False), True, "quiet")
gate("interpreter / relative symlink path keeps its environment identity",
     lambda: _interpreter_control(True), True, "quiet")

# ================= local subject paths are not subject verdicts
def _subject_path_preflight(kind):
    import contextlib
    from unittest.mock import patch
    class ReachedInspection(Exception):
        pass
    with tempfile.TemporaryDirectory() as tmp:
        subject = os.path.join(tmp, "subject")
        entry = "server.py"
        valid = kind in ("nested", "absolute")
        if kind == "file":
            with open(subject, "w") as f:
                f.write("not a directory")
        elif kind != "missing-dir":
            os.mkdir(subject)
        if valid:
            os.mkdir(os.path.join(subject, "src"))
            script = os.path.join(subject, "src", "server.py")
            with open(script, "w") as f:
                f.write("# fictional fixture\n")
            entry = script if kind == "absolute" else "src/server.py"
        err = io.StringIO()
        argv = ["run.py", "--subject-dir", subject, "--entry", entry,
                "--upstream", "fictional fixture", "--out", tmp]
        try:
            with patch.object(sys, "argv", argv), contextlib.redirect_stderr(err), \
                    patch.object(_run, "git", side_effect=ReachedInspection):
                rc = _run.main()
        except ReachedInspection:
            return valid
        return not valid and rc == 2 and "no probes ran" in err.getvalue() \
            and not any(name.endswith(".json") for name in os.listdir(tmp))

for _kind in ("missing-dir", "file", "missing-entry", "nested", "absolute"):
    gate(f"subject path / {_kind}",
         lambda k=_kind: _subject_path_preflight(k), True,
         "quiet" if _kind in ("nested", "absolute") else "detect")

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
