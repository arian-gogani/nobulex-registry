#!/usr/bin/env python3
"""
Nobulex reliability suite v0.1 -- TOOL attestation harness.
Direct MCP stdio calls. No model in the loop.

DESIGN RULE THAT MATTERS MOST
----------------------------
Classification is pure. Every classify_* function takes an observation plus
authority data and returns (outcome, loss_cause, detail). It performs no I/O.
That is what lets selftest.py prove the harness detects what it claims to
detect, by feeding it planted failures with no network involved.

SECOND RULE
-----------
Unknown state resolves to INDETERMINATE, never to PASS. Any unexpected
exception inside a probe is caught and recorded as INDETERMINATE with the
traceback attached. A harness whose failure mode is a silent pass is the
exact product defect this registry exists to detect.
"""

import json, math, re, select, subprocess, sys, time, traceback
import urllib.error, urllib.request
from datetime import datetime, timezone, timedelta

SUITE_VERSION = "reliability-v0.1"
SCHEMA_VERSION = "record-v0.4"
UA = "Nobulex-Registry/0.1 (+https://nobulex.com; nobulex.dev@gmail.com)"

# ------------------------------------------------------------------ verdicts
PASS, FAIL_SAFE, FAIL_UNSAFE, INDETERMINATE, OUT_OF_SCOPE = (
    "PASS", "FAIL_SAFE", "FAIL_UNSAFE", "INDETERMINATE", "OUT_OF_SCOPE")

# Aggregation order. FAIL_UNSAFE dominates everything: one quiet lie is not
# averaged away by ten correct answers.
_ORDER = [FAIL_UNSAFE, FAIL_SAFE, INDETERMINATE, PASS, OUT_OF_SCOPE]

def aggregate(outcomes):
    for o in _ORDER:
        if o in outcomes:
            return o
    return OUT_OF_SCOPE

# ---------------------------------------------------------------- record ids
# Record ids run in one sequence, not one sequence per day: 001 was written on
# one day, 002 and 003 on the next. This lives here, with the classifiers, and
# takes a list rather than a directory, so that the arithmetic can be tested
# without a filesystem. It is a correctness claim, and an untested correctness
# claim is a preference.
_ID = re.compile(r"^NBLX-\d{8}-(\d{3})\b")

def next_in_sequence(names, day):
    """One past the highest number in `names`, stamped with `day`.

    Counts held and withdrawn records alongside published ones, because a
    withdrawn record still spent its number, and reissuing it would point two
    different records at one identity. An empty list yields 001.
    """
    seen = [0] + [int(m.group(1))
                  for m in (_ID.match(n) for n in names) if m]
    return f"NBLX-{day}-{max(seen) + 1:03d}"

# ------------------------------------------------- pinned before execution
CONFIG = {
    "price_tolerance_rel": 0.0005,
    "price_tolerance_note": "5 basis points. This is an adapter-fidelity "
        "tolerance, not a market-movement tolerance. Both sides read the same "
        "upstream, so any deviation beyond rounding is introduced in transit.",
    "freshness_max_calendar_days": 5,
    "freshness_max_future_days": 2,
    "freshness_max_future_note": "A bar dated ahead of the run describes a "
        "session that has not happened. Two days of slack rather than zero, "
        "because a session on an exchange ahead of UTC can carry tomorrow's "
        "date while the harness clock still reads today, and a tighter bound "
        "would fail a correct tool for being in Asia. Past that there is no "
        "timezone that explains it. This is not staleness inverted: a stale "
        "bar discloses its own age in the date it carries, while a future bar "
        "is a value that nothing observed, which is fabricated_field.",
    "truncation_min_overlap_frac": 0.5,
    "truncation_min_overlap_note": "Counting sessions and checking that the "
        "windows touch at all was not enough. The no-overlap case was already "
        "graded, and a single shared date defeated it: a subject serving 100 "
        "sessions that share one day with the authority's 100 returned PASS "
        "reading 'subject 100 sessions, authority 100'. Equal counts over "
        "mostly different sessions is not a truncation result any more than "
        "equal counts over entirely different ones, so the same floor the "
        "fidelity probe uses applies here and the case resolves INDETERMINATE "
        "for the fidelity probe to judge on values.",
    "fidelity_min_overlap_frac": 0.5,
    "fidelity_min_overlap_note": "Matched dates must cover at least half of the "
        "smaller side, and at least two sessions, before any value comparison is "
        "issued. Below that, a mismatch cannot be distinguished from a date-basis "
        "misalignment, and the run resolves INDETERMINATE. A false FAIL_UNSAFE "
        "against a correct tool is the worst output this harness can produce.",
    "authorities": {
        "A1": {
            "id": "yahoo-finance-chart-v8",
            "endpoint": "https://query1.finance.yahoo.com/v8/finance/chart/",
            "role": "transport_fidelity",
            "independent_of_subject_upstream": False,
            "limitation": "This is the same upstream the subject wraps. It can "
                "detect corruption introduced by the adapter stack. It cannot "
                "detect upstream-wrong data. Probes that would require an "
                "independent price authority return OUT_OF_SCOPE, not PASS.",
        },
        "A2": {
            "id": "sec-edgar-company-tickers",
            "endpoint": "https://www.sec.gov/files/company_tickers.json",
            "role": "entity_identity",
            "independent_of_subject_upstream": True,
            "limitation": "Authoritative for ticker to registrant mapping only. "
                "Says nothing about prices.",
        },
    },
}

# ------------------------------------------------------------ MCP stdio client
class MCPStdio:
    """Minimal JSON-RPC 2.0 MCP client over stdio. No SDK dependency, so the
    harness cannot inherit a bug from the same library family as the subject."""

    def __init__(self, cmd, cwd, timeout=90):
        self.timeout = timeout
        self.proc = subprocess.Popen(
            cmd, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1)
        self._id = 0
        # Non-JSON bytes seen on the JSON-RPC channel. Evidence, not noise.
        self.protocol_noise = []
        # Filled in by close(). A subject that never answered is not one
        # observation, it is several: it may have crashed with a diagnosis on
        # stderr, or exited zero in silence, or been killed for hanging. A
        # record that cannot tell those apart is not reproducible, so both the
        # exit status and whatever the subject said on its way out are kept.
        self.returncode = None
        self.stderr_text = ""
        self._closed = False

    def _send(self, obj):
        self.proc.stdin.write(json.dumps(obj) + "\n")
        self.proc.stdin.flush()

    def _readline(self, deadline):
        remaining = deadline - time.time()
        if remaining <= 0:
            raise TimeoutError("no response within timeout")
        r, _, _ = select.select([self.proc.stdout], [], [], remaining)
        if not r:
            raise TimeoutError("no response within timeout")
        line = self.proc.stdout.readline()
        if line == "":
            raise EOFError("server closed stdout")
        return line

    def _await(self, want_id):
        deadline = time.time() + self.timeout
        while True:
            line = self._readline(deadline)
            s = line.strip()
            if not s:
                continue
            try:
                msg = json.loads(s)
            except json.JSONDecodeError:
                # The server wrote something that is not JSON onto the channel
                # reserved for JSON-RPC framing. Record it verbatim.
                self.protocol_noise.append(s[:500])
                continue
            if isinstance(msg, dict) and msg.get("id") == want_id:
                return msg

    def request(self, method, params=None):
        self._id += 1
        self._send({"jsonrpc": "2.0", "id": self._id, "method": method,
                    "params": params or {}})
        return self._await(self._id)

    def notify(self, method, params=None):
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def initialize(self):
        r = self.request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "nobulex-harness", "version": "0.1"}})
        self.notify("notifications/initialized")
        return r

    def call(self, name, arguments):
        """Returns (text, is_error_flag, raw_response)."""
        r = self.request("tools/call", {"name": name, "arguments": arguments})
        # Key presence, not truth. JSON-RPC says error must be absent on
        # success, but "error": null next to a valid result is what a struct
        # without omitempty, or a model with a nullable field, serializes to.
        # `"error" in r` read that as a refusal, discarded the body, and
        # returned is_error=True. A subject fabricating 250 bars for a ticker
        # that does not exist was then graded PASS, "refused through the
        # protocol error channel", on P01, P02 and P11, and run.py wrote the
        # same false sentence into P04 through P08 as well.
        if r.get("error") is not None:
            return None, True, r
        res = r.get("result", {})
        parts = [c.get("text", "") for c in res.get("content", [])
                 if c.get("type") == "text"]
        # bool("false") is True, and so is bool("0") and bool("no"). A subject
        # serializing the flag as a string got the same PASS flip by a
        # different route. Only the two real booleans are an answer here.
        # Anything else is unknown state, and unknown state resolves toward the
        # finding rather than away from it, so it is reported as an error flag
        # the caller cannot rely on rather than silently coerced.
        flag = res.get("isError")
        if flag is True or flag is False:
            is_error = flag
        else:
            is_error = False
            if flag is not None:
                self.protocol_noise.append(
                    "isError was %r, which is neither true nor false"
                    % (flag,))
        return "\n".join(parts), is_error, r

    def close(self):
        # Idempotent. The runner closes early when startup fails, so it can put
        # the subject's own diagnosis into the probe rather than only the
        # harness's view of it, and closes again in its finally block. A second
        # read of a drained pipe returns nothing, and overwriting the captured
        # stderr with that nothing would discard the only evidence there is.
        if self._closed:
            return self.stderr_text
        self._closed = True
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()
            try:
                self.proc.wait(timeout=5)
            except Exception:
                pass
        try:
            self.stderr_text = self.proc.stderr.read() or ""
        except Exception:
            self.stderr_text = ""
        self.returncode = self.proc.returncode
        return self.stderr_text

    def exit_summary(self):
        """One line describing how the subject process ended, for the record."""
        rc = self.returncode
        if rc is None:
            return "process status unavailable"
        if rc == 0 and not self.stderr_text.strip():
            return ("exited 0 and wrote nothing to stderr, so it gave no "
                    "account of itself")
        if rc == 0:
            return "exited 0 with output on stderr"
        if rc < 0:
            return f"killed by signal {-rc}"
        return f"exited {rc}"

# ------------------------------------------------------------- authorities
class AuthorityUnavailable(Exception):
    """Raised when an authority could not be read.

    "Unreachable" is not a finding a reader can check. A 429 is the authority
    throttling this harness, a 404 is the endpoint having moved, and a name
    resolution failure is the machine the harness ran on having no route out.
    Those are three different facts about three different parties, and a record
    that collapses them into one word cannot be audited. The status, the reason,
    the attempt count and a short body excerpt travel with the exception so all
    of them reach the record."""

    def __init__(self, url, status=None, reason=None, body_excerpt=None,
                 attempts=1):
        self.url, self.status = url, status
        self.reason, self.body_excerpt = reason, body_excerpt
        self.attempts = attempts
        super().__init__(f"{url} status={status} reason={reason} "
                         f"attempts={attempts}")

    def as_dict(self):
        return {"url": self.url, "http_status": self.status,
                "reason": self.reason, "body_excerpt": self.body_excerpt,
                "attempts": self.attempts}


AUTHORITY_ATTEMPTS = 3
AUTHORITY_BACKOFF_S = (0, 2, 5)
# Statuses worth a second attempt. Everything else is the authority stating a
# fact about the request itself, and repeating an identical request cannot
# change that answer.
_RETRYABLE = (408, 429, 500, 502, 503, 504)


def _get_json(url, ua=UA, timeout=25, attempts=AUTHORITY_ATTEMPTS):
    """Read an authority endpoint as JSON.

    The harness identifies itself by name. It does not present a browser user
    agent: a registry whose product is accountability cannot spoof its own
    identity to the sources it cites, and in the one case where the temptation
    was real the upstream throttled the browser string exactly the same.

    Retries are bounded and the count is recorded. Retrying without a bound
    would turn a throttled authority into a hung run, and a run that never
    finishes produces no record at all, which is worse than a record that says
    the authority declined to answer three times."""
    last = None
    for i in range(attempts):
        delay = AUTHORITY_BACKOFF_S[min(i, len(AUTHORITY_BACKOFF_S) - 1)]
        if i and delay:
            time.sleep(delay)
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": ua, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as fh:
                return json.loads(fh.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")[:200]
            except Exception:
                pass
            last = AuthorityUnavailable(url, status=e.code,
                                        reason=str(e.reason),
                                        body_excerpt=body, attempts=i + 1)
            if e.code not in _RETRYABLE:
                raise last
        except Exception as e:
            last = AuthorityUnavailable(url, status=None,
                                        reason=f"{type(e).__name__}: {e}",
                                        attempts=i + 1)
    raise last

def a1_chart(ticker, rng="5d", interval="1d"):
    """Authority A1. Returns {'symbol', 'tz_basis', 'bars':[{...,'date'}]}.

    A daily bar's timestamp is the session open in exchange-local time. The
    subject indexes the same sessions by their exchange-local calendar date.
    Converting the authority's timestamps in UTC therefore silently shifts the
    date by one for any exchange whose session opens after 00:00 UTC minus its
    offset, which would make a correct tool look like it returned the previous
    session's numbers. Date derivation happens here, where the timezone the
    upstream itself asserts is available, and not inside a pure classifier that
    has no way to know it."""
    url = (f"{CONFIG['authorities']['A1']['endpoint']}{ticker}"
           f"?range={rng}&interval={interval}")
    d = _get_json(url)
    # The three shapes below are ordinary answers from this endpoint, not
    # corrupt ones, and each used to raise a bare TypeError, KeyError or
    # IndexError out of here. run.py catches broadly so the run survived, but
    # what it then wrote into the record was reachable: false with a reason of
    # "TypeError: 'NoneType' object is not subscriptable". The authority was
    # reached and did answer; it answered that the symbol has no data. A record
    # that calls that unreachable states something untrue about a third party's
    # service, and the reason field names a Python type instead of what the
    # upstream said. AuthorityUnavailable carries the upstream's own words.
    chart = d.get("chart") if isinstance(d, dict) else None
    if not isinstance(chart, dict):
        raise AuthorityUnavailable(url, status=200,
                                   reason="response has no chart object")
    results = chart.get("result")
    if not results:
        err = chart.get("error") or {}
        detail = err.get("description") or err.get("code") or "no result and no error given"
        raise AuthorityUnavailable(url, status=200,
                                   reason=f"authority answered with no result: {detail}",
                                   body_excerpt=str(err)[:200])
    res = results[0]
    meta = res.get("meta", {})
    if "timestamp" not in res:
        raise AuthorityUnavailable(url, status=200,
                                   reason="authority returned a result with no "
                                          "timestamp array, so there are no "
                                          "sessions in this window")
    try:
        q = res["indicators"]["quote"][0]
    except (KeyError, IndexError, TypeError):
        raise AuthorityUnavailable(url, status=200,
                                   reason="authority returned timestamps with "
                                          "no matching quote block")

    tzname = meta.get("exchangeTimezoneName")
    tz, tz_basis = None, None
    if tzname:
        try:
            from zoneinfo import ZoneInfo
            tz, tz_basis = ZoneInfo(tzname), f"exchange tz {tzname}"
        except Exception:
            tz = None
    if tz is None and isinstance(meta.get("gmtoffset"), int):
        tz = timezone(timedelta(seconds=meta["gmtoffset"]))
        tz_basis = f"fixed offset {meta['gmtoffset']}s asserted by upstream"
    if tz is None:
        tz, tz_basis = timezone.utc, "UTC fallback, exchange timezone unstated"

    stamps = res["timestamp"]
    # Ragged arrays used to raise IndexError on the first short one. Taking the
    # shortest common length instead would silently drop sessions, so this
    # refuses: a partial read of the authority is not something to compare a
    # subject against, and it is exactly the "empty comparison is not a clean
    # bill of health" rule applied to the other side of the comparison.
    for k in ("open", "high", "low", "close"):
        col = q.get(k)
        if not isinstance(col, list) or len(col) != len(stamps):
            raise AuthorityUnavailable(
                url, status=200,
                reason=f"authority returned {len(stamps)} timestamps but "
                       f"{len(col) if isinstance(col, list) else 'no'} {k} "
                       f"values; a ragged read cannot be compared against")
    bars = []
    for i, ts in enumerate(stamps):
        bars.append({"ts": ts,
                     "date": datetime.fromtimestamp(ts, tz).strftime("%Y-%m-%d"),
                     "open": q["open"][i], "high": q["high"][i],
                     "low": q["low"][i], "close": q["close"][i]})
    return {"symbol": meta.get("symbol", ticker), "tz_basis": tz_basis,
            "bars": bars}

_EDGAR_CACHE = {}
def a2_edgar(ticker):
    """Authority A2. Returns registrant title for a ticker, or None.

    The read is built into a local dict and only published to the cache once it
    finishes. It used to write rows into _EDGAR_CACHE as it walked them, so a
    read that died partway left the cache non-empty, `if not _EDGAR_CACHE` was
    false ever after, and no later call retried. Every ticker missing from the
    fragment then returned None, which classify_entity reports as OUT_OF_SCOPE,
    "ticker not present in the SEC registrant file" -- a claim about the SEC's
    file derived from a read that failed. A None here has to mean the authority
    said so, not that the harness stopped listening."""
    if not _EDGAR_CACHE:
        d = _get_json(CONFIG["authorities"]["A2"]["endpoint"])
        if not isinstance(d, dict) or not d:
            raise AuthorityUnavailable(
                CONFIG["authorities"]["A2"]["endpoint"], status=200,
                reason="registrant file was not a non-empty object")
        built, skipped = {}, 0
        for row in d.values():
            try:
                built[row["ticker"].upper()] = row["title"]
            except (KeyError, AttributeError, TypeError):
                skipped += 1
        if not built:
            raise AuthorityUnavailable(
                CONFIG["authorities"]["A2"]["endpoint"], status=200,
                reason=f"no usable rows in the registrant file "
                       f"({skipped} unreadable)")
        if skipped > len(built) * 0.01:
            raise AuthorityUnavailable(
                CONFIG["authorities"]["A2"]["endpoint"], status=200,
                reason=f"{skipped} of {skipped + len(built)} registrant rows "
                       f"were unreadable, so an absent ticker cannot be "
                       f"distinguished from a partial read")
        _EDGAR_CACHE.update(built)
    return _EDGAR_CACHE.get(ticker.upper())

# ------------------------------------------------------- pure classification
_SUFFIX = re.compile(
    r"\b(inc|incorporated|corp|corporation|co|company|ltd|limited|plc|"
    r"holdings|group|the|sa|nv|ag|class|common|stock)\b")

# Decorations an exchange or a data vendor appends to the name of a security
# without naming a different legal entity: share class, instrument type,
# depositary wrappers. Stripped from both sides of every comparison, so they
# can only make two names agree, never make them differ.
_DECOR = re.compile(
    r"\b(shares|share|ordinary|adr|ads|sponsored|unsponsored|depositary|"
    r"depository|receipts|receipt|series|new)\b")

def _norm_name(s):
    s = re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())
    s = _SUFFIX.sub(" ", s)
    s = _DECOR.sub(" ", s)
    # A one-character token cannot distinguish two companies. Left in, it is
    # almost always the share-class letter that survives stripping "class"
    # ("Alphabet Inc. Class A" -> {alphabet, a}). Dropped from both sides.
    return set(t for t in s.split() if len(t) > 1)

def parse_bars(text):
    """Parse the subject's historical-prices payload. Returns (bars, note).
    bars is None when the payload is not the documented JSON record array."""
    try:
        obj = json.loads(text)
    except Exception:
        return None, "payload is not JSON"
    if not isinstance(obj, list):
        return None, "payload is JSON but not a record array"
    return obj, None

def classify_absent_entity(text, is_error, parsed):
    """Probe: a ticker that does not exist.
    Loud refusal is the correct behavior. An empty array is not."""
    if is_error:
        return PASS, None, "refused through the protocol error channel"
    if parsed is not None and isinstance(parsed, list):
        if len(parsed) == 0:
            return (FAIL_UNSAFE, "silent_empty",
                    "returned an empty record array as a successful result. A "
                    "caller cannot distinguish this from a stock with no trades.")
        return (FAIL_UNSAFE, "fabricated_field",
                f"returned {len(parsed)} records for an entity that does not exist")
    if text and re.search(r"not found|error|invalid|no data|unknown",
                          text, re.I):
        return (FAIL_SAFE, "unsignaled_fallback",
                "said 'not found' in prose on the success channel. The failure "
                "is legible to a human reader but carries no isError flag, so a "
                "programmatic caller must string-match to detect it.")
    return INDETERMINATE, None, "response neither an error nor a parseable payload"

def classify_empty_window(text, is_error, parsed):
    """Probe: a request whose documented constraints guarantee no data."""
    if is_error:
        return PASS, None, "refused through the protocol error channel"
    if parsed is not None and isinstance(parsed, list) and len(parsed) == 0:
        return (FAIL_UNSAFE, "silent_empty",
                "returned [] as a successful result for a request the tool's "
                "own description says cannot be satisfied")
    if text and re.search(r"not found|error|invalid|no data|cannot", text, re.I):
        return FAIL_SAFE, None, "declined in prose on the success channel"
    if parsed:
        return PASS, None, f"returned {len(parsed)} records"
    return INDETERMINATE, None, "unclassifiable response"

def classify_invalid_argument(text, is_error, parsed, arg_desc):
    """Probe: an argument with no valid interpretation under any reading.

    PRECONDITION, and the reason this docstring is long: the caller must have
    established that the argument is genuinely unhonorable, not merely absent
    from the documented enumeration. Those are different things, and conflating
    them produced a false FAIL_UNSAFE the first time this ran. period='13y' is
    undocumented, and the subject served exactly thirteen years for it; calling
    that a silent fallback was an accusation about a substitution that never
    happened. period='banana' has no reading under which data is a correct
    answer, so for arguments of that kind, and only those, the presence of data
    is itself the evidence.

    Where the argument does have a possible reading, use classify_window_span
    instead, which measures what was served rather than inferring from the fact
    that something was."""
    if is_error:
        return PASS, None, f"rejected {arg_desc} through the error channel"
    if text and re.search(r"invalid|not a valid|must be one of|error", text, re.I):
        return FAIL_SAFE, None, f"rejected {arg_desc} in prose, not via isError"
    if parsed is not None and isinstance(parsed, list) and len(parsed) > 0:
        return (FAIL_UNSAFE, "unsignaled_fallback",
                f"accepted {arg_desc}, which has no valid interpretation, and "
                f"returned {len(parsed)} records anyway. "
                "The caller believes it received the data it asked for.")
    if parsed is not None and isinstance(parsed, list):
        return (FAIL_UNSAFE, "silent_empty",
                f"accepted {arg_desc} and returned an empty array with no signal")
    return INDETERMINATE, None, "unclassifiable response"

def classify_padded_argument(padded_text, padded_err, padded_bars,
                             base_text, base_err, base_bars, arg_desc):
    """Probe: does a whitespace-padded argument quietly serve something else?

    THE PRECONDITION THIS EXISTS TO HONOR, and why it is not a variant of
    classify_invalid_argument.

    A trailing space is not an argument with no valid interpretation. It has
    one, it is obvious, and it is the one every reasonable tool applies:
    strip it. A tool that strips '1mo ' and serves one month is CORRECT.

    Routing this through classify_invalid_argument asserted the opposite. That
    classifier's contract is that the presence of data is itself the evidence,
    which is only sound when no reading of the argument makes data a correct
    answer. Whitespace fails that test completely, so the probe returned
    FAIL_UNSAFE unsignaled_fallback, "which has no valid interpretation",
    against essentially every well-behaved subject. Published, that is an
    accusation of a silent fallback levelled at a maintainer whose tool did
    the ordinary right thing, and a false FAIL_UNSAFE against a correct tool
    is the worst output this harness can produce.

    The probe's own comment always described the honest test: if the padded
    and unpadded forms disagree, the disagreement should be audible. It just
    never fetched the unpadded form to compare against. This does, so the
    finding rests on an observed difference rather than on an inference from
    the mere existence of a response.

    Refusal is a pass. Strictly rejecting a malformed argument is a legitimate
    design, and so is tolerating it. Only silently serving something DIFFERENT
    while reporting success is the failure."""
    if padded_err:
        return (PASS, None,
                f"refused {arg_desc} through the error channel. Strict "
                f"rejection of a padded argument is a legitimate design")
    if padded_text and re.search(r"invalid|not a valid|must be one of",
                                 padded_text, re.I):
        return (FAIL_SAFE, None,
                f"declined {arg_desc} in prose on the success channel rather "
                f"than through isError, so a programmatic caller must string "
                f"match to notice")
    if base_err or base_bars is None:
        return (INDETERMINATE, None,
                f"the unpadded control could not be read, so there is nothing "
                f"to compare {arg_desc} against and no claim is issued")
    if padded_bars is None:
        return (INDETERMINATE, None,
                f"the response to {arg_desc} was not the documented record "
                f"array, so it could not be compared to the unpadded control")

    def shape(bars):
        return (len(bars),
                tuple(sorted(str(b.get("Date", ""))[:10]
                             for b in bars if isinstance(b, dict))))

    p, b = shape(padded_bars), shape(base_bars)
    # Empty against a control that served is its own cause. The two held
    # records that carry this probe both landed here, and calling it a
    # fallback would describe a substitution that did not happen: nothing was
    # served in place of the window, nothing was served at all. silent_empty
    # is what that is, and it is the cause those records already name.
    if b[0] == 0:
        # The control served nothing either, so the padding made no observable
        # difference and there is no baseline to compare against. Reporting
        # PASS here would read "the same 0 sessions over the same dates",
        # which is a pass asserting an agreement between two absences. The
        # subject's failure on the unpadded request is P04 through P08's to
        # describe, not this probe's.
        return (INDETERMINATE, None,
                f"the unpadded control returned no sessions either, so the "
                f"padding made no observable difference and this probe "
                f"establishes nothing about {arg_desc}")
    if p[0] == 0 and b[0] > 0:
        return (FAIL_UNSAFE, "silent_empty",
                f"{arg_desc} returned an empty array with no signal, where "
                f"the unpadded control returned {b[0]} sessions. The padding "
                f"has an obvious reading and the subject reported success "
                f"while honoring neither it nor the argument under it")
    if p == b:
        return (PASS, None,
                f"{arg_desc} and the unpadded control returned the same "
                f"{p[0]} sessions over the same dates, so the padding was "
                f"tolerated and nothing was substituted")
    return (FAIL_UNSAFE, "unsignaled_fallback",
            f"{arg_desc} returned {p[0]} sessions where the unpadded control "
            f"returned {b[0]}, and the served dates differ, with success "
            f"reported both times. The caller believes it received the window "
            f"it asked for")


def classify_window_span(text, is_error, parsed, requested_days, arg_desc,
                         available_days=None, tol_frac=0.10):
    """Probe: did the subject serve less than it had, and say nothing?

    THE PRECONDITION, AND WHY IT IS NOT OPTIONAL
    A window shorter than the one requested has two possible causes, and the
    response cannot tell them apart: the subject withheld data it holds, or the
    data does not exist. Only the first is a failure. Serving every bar that
    exists is the complete and correct answer to a request for more history
    than the world contains.

    This classifier was written after a false FAIL_UNSAFE was caught before
    publication, and its first version was ALSO false for exactly this reason:
    it read a 46%-of-request span for AAPL as a silent cap, when 1980-12-12 is
    simply the day AAPL listed. Ten older listings served 1962 under the same
    request, which is how the second false verdict was caught. A shortfall is
    not evidence of anything until you know what was available.

    So available_days is the whole classifier. Without it a shortfall is
    INDETERMINATE, never a finding, because the accusation cannot be supported.
    With it, the claim is precise: the subject's own reachable history was N
    days, the caller asked for more than N, and fewer than N came back with no
    field naming what was delivered.

    The honest way to source available_days is the subject's own documented
    maximum, which makes this a self-consistency test rather than a claim about
    the world. That is deliberately the weaker claim, and it is the strongest
    one the evidence supports: if the documented maximum is itself a lie, that
    is a different failure this probe does not measure and does not assert.

    A window LONGER than requested is not a finding in any case. Every bar the
    caller asked for is present, so nothing they compute from it is wrong."""
    if is_error:
        return PASS, None, f"rejected {arg_desc} through the error channel"
    if text and re.search(r"invalid|not a valid|must be one of", text, re.I):
        return FAIL_SAFE, None, f"rejected {arg_desc} in prose, not via isError"
    if parsed is None or not isinstance(parsed, list):
        return INDETERMINATE, None, "unclassifiable response"
    if not parsed:
        return (FAIL_UNSAFE, "silent_empty",
                f"accepted {arg_desc} and returned an empty array with no signal")
    if (not isinstance(requested_days, (int, float))
            or isinstance(requested_days, bool)
            or not math.isfinite(requested_days)
            or requested_days <= 0):
        # ratio divides by this. A zero-length request is not a window anyone
        # can be short of, and it used to raise ZeroDivisionError out of the
        # classifier, which run.py's boundary turns into a failed run that
        # loses every other probe's result along with it.
        #
        # isfinite is here because nan cleared the old guard and then produced
        # a false accusation. nan <= 0 is False, so it passed; ratio became
        # nan; nan >= 1.0 - tol was False, so the short path ran; min(nan, av)
        # returned nan; served >= nan was False; and the classifier returned
        # FAIL_UNSAFE partial_truncation about a subject that had served the
        # full window. Every comparison failed open in the direction of an
        # accusation, which is the one direction this harness must not fail in.
        return (INDETERMINATE, None,
                f"requested_days is {requested_days!r}, which is not a window "
                f"a subject can serve less of; no span claim is issued")
    # The subject's own field name, matching classify_monotonic. Reading a key
    # the payload does not have would measure nothing and quietly return PASS,
    # which is the vacuous-verdict defect this probe exists to avoid.
    dated = [str(b.get("Date", ""))[:10] for b in parsed
             if isinstance(b, dict) and b.get("Date")]
    dates = sorted(dated)
    if len(dates) < 2:
        return (INDETERMINATE, None,
                "fewer than two dated records, so the served span cannot be "
                "measured and no claim is issued in either direction")
    # strptime below is %Y-%m-%d and nothing checked that first, so a payload
    # dating its bars any other way raised ValueError out of the classifier.
    # classify_monotonic already refuses non-ISO dates rather than ordering
    # them wrongly; this refuses them rather than crashing on them.
    bad = [d for d in dates if not ISO_DATE.match(d)]
    if bad:
        return (INDETERMINATE, None,
                f"{len(bad)} of {len(dates)} dates are not ISO 8601 "
                f"(first: {bad[0]!r}), so the served span cannot be measured")
    served = (datetime.strptime(dates[-1], "%Y-%m-%d")
              - datetime.strptime(dates[0], "%Y-%m-%d")).days
    ratio = served / float(requested_days)
    # len(dated), not len(parsed). The span is measured from the dated records
    # only, and citing the total made the evidence claim a wider basis than the
    # measurement had: nine dated bars and three undated ones read as "across
    # 12 records".
    undated = len(parsed) - len(dated)
    ev = (f"requested {arg_desc} ({requested_days} days), served {served} days "
          f"across {len(dated)} dated records"
          + (f" ({undated} undated records ignored)" if undated else "")
          + f", {dates[0]} to {dates[-1]}, {ratio:.1%} of the request")

    if ratio >= 1.0 - tol_frac:
        return PASS, None, f"the requested window was served in full: {ev}"

    # Short. Everything below decides whether that is the subject's fault, and
    # the default when it cannot be decided is to make no accusation.
    if available_days is None:
        return (INDETERMINATE, None,
                f"the served window is short, but how much history the subject "
                f"could reach was not measured, so this cannot be attributed "
                f"to the subject rather than to the data not existing: {ev}")

    if (not isinstance(available_days, (int, float))
            or isinstance(available_days, bool)
            or not math.isfinite(available_days)
            or available_days <= 0):
        # available_days is the whole basis for attributing a shortfall, and a
        # value of zero or less is not a measurement of reachable history, it
        # is the absence of one. Left unchecked it produced a vacuous pass:
        # owed became min(requested, 0) = 0, served >= 0 held for every
        # payload, and the classifier reported "the request was honored to the
        # limit of what the subject could reach (0 days available, 0 owed)"
        # about a subject that had just served 364 days. A sentence that
        # explains away a shortfall using a limit nobody measured is worse
        # than no sentence.
        return (INDETERMINATE, None,
                f"the served window is short, and available_days is "
                f"{available_days!r}, which is not a measurement of reachable "
                f"history, so the shortfall cannot be attributed: {ev}")
    owed = min(requested_days, available_days)
    if served >= owed * (1.0 - tol_frac):
        return (PASS, None,
                f"the request was honored to the limit of what the subject "
                f"could reach ({available_days} days available, {owed} owed), "
                f"which is the complete answer to a request for more history "
                f"than exists: {ev}")

    return (FAIL_UNSAFE, "partial_truncation",
            f"the subject reported success while serving a strict subset of "
            f"the history it can reach, with no field naming the window "
            f"actually delivered: {ev}, against {available_days} days the "
            f"subject served for the same entity under its own documented "
            f"maximum. A caller computing over the period it requested is "
            f"computing over a different period and cannot tell.")

def _auth_date(b):
    """Exchange-local session date, precomputed by a1_chart. The UTC fallback
    exists only for hand-built fixtures and is flagged where it is used."""
    d = b.get("date")
    if d:
        return d
    return datetime.fromtimestamp(b["ts"], timezone.utc).strftime("%Y-%m-%d")

def classify_fidelity(subject_bars, authority_bars, tol,
                      min_overlap=None):
    """Probe: does the adapter stack transmit the upstream's own numbers?

    Refuses to issue a value verdict when the two sides' dates do not line up
    well enough to tell corruption from a date-basis misalignment."""
    if min_overlap is None:
        min_overlap = CONFIG["fidelity_min_overlap_frac"]
    if not subject_bars:
        return INDETERMINATE, None, "subject returned no bars to compare"
    if not authority_bars:
        return INDETERMINATE, None, "authority returned no bars to compare"
    sub = {}
    unreadable = 0
    for b in subject_bars:
        if not isinstance(b, dict):
            unreadable += 1
            continue
        d = str(b.get("Date", ""))[:10]
        c = b.get("Close")
        if d and _numeric(c):
            sub[d] = c
        else:
            unreadable += 1
    auth = {}
    auth_unreadable = 0
    for b in authority_bars:
        # _numeric, not "is not None". The subject's closes were routed through
        # _numeric and the authority's were not, so the nan hole that _numeric
        # exists to close stayed open on this side of the comparison. json.loads
        # accepts the bare token NaN, so it arrives here from the wire intact.
        #
        # The consequence is identical to the subject-side bug and reaches the
        # same evidence string: nan == 0 is False so the session counts as
        # compared, rel is nan, nan > worst is False so worst never leaves 0.0,
        # and the probe returns PASS reading "worst deviation 0.00000% within
        # tolerance". An authority column of nan hides subject corruption on
        # every session it covers.
        if not _numeric(b.get("close")):
            auth_unreadable += 1
            continue
        auth[_auth_date(b)] = b["close"]
    common = sorted(set(sub) & set(auth))
    # Measured against what the subject actually sent, not against what survived
    # parsing. Using len(sub) meant a payload whose closes were unreadable got a
    # BETTER overlap ratio for having been dropped: three of five bars arriving
    # as strings left two clean ones, two of two aligned, and the floor was
    # satisfied by discarding the evidence against it.
    smaller = min(len(subject_bars), len(auth))
    if auth_unreadable and not auth:
        return (INDETERMINATE, None,
                f"all {auth_unreadable} authority bars carried no readable "
                f"numeric close, so there was nothing to compare the subject "
                f"against and no fidelity claim is issued")
    if not common:
        return (INDETERMINATE, None,
                f"no overlapping dates. subject={sorted(sub)[:3]} "
                f"authority={sorted(auth)[:3]}")
    if len(common) < 2 or (smaller and len(common) < smaller * min_overlap):
        return (INDETERMINATE, None,
                f"only {len(common)} of {smaller} sessions align by date "
                f"(subject={sorted(sub)[:3]} authority={sorted(auth)[:3]}). "
                "Below the pinned overlap floor, a value mismatch cannot be "
                "separated from a date-basis misalignment, so no fidelity "
                "verdict is issued.")
    worst, worst_d = 0.0, None
    compared = 0
    for d in common:
        if auth[d] == 0:
            continue
        compared += 1
        rel = abs(sub[d] - auth[d]) / abs(auth[d])
        if rel > worst:
            worst, worst_d = rel, d
    if compared == 0:
        # Every aligned session had an authority close of zero, so the relative
        # deviation was undefined for all of them and none was measured. This
        # used to fall through with worst still 0.0 and report "worst deviation
        # 0.00000% within tolerance" about zero comparisons.
        return (INDETERMINATE, None,
                f"{len(common)} sessions aligned by date but the authority "
                f"close was zero for every one of them, so relative deviation "
                f"was undefined and nothing was compared")
    if worst > tol:
        lag = _uniform_lag(sub, auth, tol)
        if lag:
            return (INDETERMINATE, None,
                    f"the subject's series matches the authority's at a uniform "
                    f"lag of {lag:+d} session(s) and not at lag 0. That is the "
                    "fingerprint of a calendar-date basis mismatch between the "
                    "two sides, not of a tool returning wrong numbers. No "
                    "fidelity verdict is issued until the date basis is "
                    "reconciled.")
        return (FAIL_UNSAFE, "stale_value",
                f"close for {worst_d} deviates {worst*100:.4f}% from the same "
                f"upstream read directly (subject={sub[worst_d]}, "
                f"authority={auth[worst_d]}), beyond the {tol*100:.2f}% pinned "
                "tolerance")
    if unreadable:
        return (INDETERMINATE, None,
                f"{unreadable} of {len(subject_bars)} subject bars carried no "
                f"readable numeric Close and were not compared; {compared} "
                f"sessions were, worst deviation {worst*100:.5f}%. A payload "
                f"that is partly unreadable is not a payload that agreed")
    return (PASS, None,
            f"{compared} overlapping sessions compared, worst deviation "
            f"{worst*100:.5f}% within tolerance")

def _uniform_lag(sub, auth, tol):
    """Return a nonzero session lag that explains the subject's series, or None.

    A tool that returns wrong numbers produces scattered deviations. A date
    basis that is off by one session produces a series that matches the
    authority perfectly once shifted. Distinguishing these is the difference
    between a published FAIL_UNSAFE and a false accusation, so it is checked
    before the verdict, not after somebody complains."""
    order = sorted(auth)
    pos = {d: i for i, d in enumerate(order)}
    for lag in (-1, 1):
        matched = compared = 0
        for d, sv in sub.items():
            i = pos.get(d)
            if i is None:
                continue
            j = i + lag
            if not (0 <= j < len(order)):
                continue
            av = auth[order[j]]
            if av == 0:
                continue
            compared += 1
            if abs(sv - av) / abs(av) <= tol:
                matched += 1
        if compared >= 2 and matched == compared:
            return lag
    return None

def _numeric(v):
    """True only for a real number. bool is excluded: True would compare as 1.

    nan and inf are excluded too, and they are the reason this docstring was
    a lie before it was a specification. Both are instances of float, so both
    were admitted as prices, and each broke a different comparison:

    nan silently passed everything. Every comparison against nan is False, so
    in classify_ohlc `not (l <= min(o, c) ...)` was True and the bar was called
    an inequality violation, while in classify_fidelity `rel > worst` was False
    and `worst` never moved off 0.0. A payload whose every close was nan
    returned PASS reporting "4 overlapping sessions compared, worst deviation
    0.00000% within tolerance". Nothing was compared. The evidence string
    asserted the comparison that the nan had just prevented.

    inf passed classify_ohlc, where `h >= max(o, c)` and `l <= h` both hold
    with an infinite high, so a bar with an infinite price was internally
    consistent.

    Excluded here rather than at each call site so that a third caller cannot
    inherit the same hole. Both now fall to the unreadable path, which is
    INDETERMINATE, which dominates PASS. That is the correct verdict: a price
    that is nan or inf was not read, and a probe that cannot read a value has
    not established anything about it."""
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and math.isfinite(v))

def classify_ohlc(bars):
    """Probe: internal consistency. low <= open,close <= high.

    A null price is skipped and not called fabrication, which is right and is
    pinned by the self-test: nulls are ordinary in real payloads. Everything
    else this probe could not read was being skipped on the same path, and then
    len(bars) was reported as the number checked. Three corrupted payloads
    reached PASS through that: a payload that was a list of integers, prices
    delivered as strings so that '10' <= '9' compared true and hid a Low above
    its High, and one bar misspelling a key so that Low 40 against Close 5.5
    was never seen. A fourth reached PASS by being null the whole way down,
    where the skip rule is correct per bar and the conclusion is not, because
    nothing was compared at all.

    So a bar that is unreadable for any reason other than a null now resolves to
    INDETERMINATE, which dominates PASS; a payload where nothing was comparable
    is INDETERMINATE however it got that way; and the evidence string counts
    what was compared rather than what arrived."""
    if not bars:
        return INDETERMINATE, None, "no bars"
    bad = []
    checked = 0
    nulled = 0
    unreadable = 0
    for b in bars:
        if not isinstance(b, dict):
            unreadable += 1
            continue
        try:
            o, h, l, c = b["Open"], b["High"], b["Low"], b["Close"]
        except Exception:
            unreadable += 1
            continue
        quad = (o, h, l, c)
        if any(v is None for v in quad):
            nulled += 1
            continue
        if not all(_numeric(v) for v in quad):
            unreadable += 1
            continue
        checked += 1
        if not (l <= min(o, c) and h >= max(o, c) and l <= h):
            bad.append(str(b.get("Date"))[:10])
    if bad:
        return (FAIL_UNSAFE, "fabricated_field",
                f"{len(bad)} bars violate low<=open,close<=high: {bad[:5]}")
    if unreadable:
        return (INDETERMINATE, None,
                f"{unreadable} of {len(bars)} bars carried no readable numeric "
                f"OHLC quadruple, so internal consistency was not established "
                f"for them; {checked} compared, {nulled} skipped as null")
    if checked == 0:
        return (INDETERMINATE, None,
                f"no bar of {len(bars)} carried a comparable OHLC quadruple "
                f"({nulled} skipped as null), so nothing was checked")
    return (PASS, None,
            f"{checked} bars internally consistent"
            + (f", {nulled} skipped as null" if nulled else ""))

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

def classify_monotonic(bars):
    """Probe: dates strictly increasing.

    The ordering test is a string sort, which is chronological for ISO 8601 and
    for nothing else. Two bars dated 01/05/2026 and 02/03/2025, in that order,
    sorted as strings look increasing and are fourteen months backwards. So the
    format is now checked before the order is, and a payload this probe cannot
    order chronologically is INDETERMINATE rather than PASS."""
    if not bars:
        return INDETERMINATE, None, "no bars"
    ds = [str(b.get("Date", ""))[:10] for b in bars if isinstance(b, dict)]
    ds = [d for d in ds if d]
    if len(ds) < 2:
        return OUT_OF_SCOPE, None, "fewer than two dated bars"
    unparseable = [d for d in ds if not ISO_DATE.match(d)]
    if unparseable:
        return (INDETERMINATE, None,
                f"{len(unparseable)} of {len(ds)} dates are not ISO 8601 "
                f"(first: {unparseable[0]!r}), so a lexical sort does not "
                f"establish chronological order")
    if ds != sorted(ds) or len(set(ds)) != len(ds):
        return (FAIL_UNSAFE, "schema_drift",
                "dates are not strictly increasing")
    return PASS, None, f"{len(ds)} dates strictly increasing"

def classify_freshness(bars, now_utc, max_days, max_future_days=None):
    """Probe: is the most recent bar recent, and does it exist yet.

    The second half was missing and is not a variant of the first. `age` is
    signed, so a bar dated ahead of the run produced a negative age, `age >
    max_days` was false, and the probe returned PASS. Bars dated a year out
    passed this, passed classify_monotonic because they were ordered, and
    passed classify_ohlc because their values were internally consistent. A
    tool emitting future sessions from a date bug or an undisclosed synthetic
    fallback collected a clean sweep, which is the exact shape this registry
    exists to catch: well formed, plausible, materially wrong, no signal.

    Staleness and future-dating are graded apart because they are different
    claims. A stale bar is a real observation that is old, and it discloses
    its own age in the date it carries. A future bar was observed by nobody,
    so it is fabricated_field rather than stale_value."""
    if not bars:
        return INDETERMINATE, None, "no bars"
    ds = sorted(str(b.get("Date", ""))[:10] for b in bars if b.get("Date"))
    if not ds:
        return INDETERMINATE, None, "no parseable dates"
    # The same rule classify_monotonic already states: a string sort is
    # chronological for ISO 8601 and for nothing else. This probe took the
    # last element of a lexical sort and called it the most recent bar, and
    # strptime is lenient about zero padding, so an unpadded date was accepted
    # after being sorted to the wrong end.
    #
    # It failed toward an accusation. '2026-1-5' sorts after '2026-09-09'
    # because '1' > '0' at the fifth character, strptime read it as 5 January,
    # and the probe returned FAIL_UNSAFE stale_value reading "most recent bar
    # is 2026-1-5, 248 calendar days old" about a payload whose newest bar was
    # the previous day. It failed the other way too: a date this probe could
    # not read at all, '09/09/2026', sorted to the front and was silently
    # dropped, and the probe passed while reporting on a payload it had only
    # partly read.
    #
    # A payload whose dates cannot be ordered chronologically supports no
    # freshness claim in either direction.
    bad = [d for d in ds if not ISO_DATE.match(d)]
    if bad:
        return (INDETERMINATE, None,
                f"{len(bad)} of {len(ds)} dates are not ISO 8601 "
                f"(first: {bad[0]!r}), so a lexical sort does not establish "
                f"which bar is the most recent and no freshness claim is made")
    try:
        latest = datetime.strptime(ds[-1], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        return INDETERMINATE, None, f"unparseable date {ds[-1]}"
    age = (now_utc - latest).days
    if max_future_days is None:
        max_future_days = CONFIG["freshness_max_future_days"]
    if age < -max_future_days:
        return (FAIL_UNSAFE, "fabricated_field",
                f"most recent bar is dated {ds[-1]}, {-age} calendar days "
                f"ahead of the run, past the {max_future_days} day pinned "
                f"allowance for exchanges ahead of UTC. A bar dated after the "
                f"run describes a session that has not happened")
    if age > max_days:
        return (FAIL_UNSAFE, "stale_value",
                f"most recent bar is {ds[-1]}, {age} calendar days old, past the "
                f"{max_days} day pinned bound")
    return PASS, None, f"most recent bar {ds[-1]}, {age} calendar days old"

def classify_entity(info_text, registrant):
    """Probe: does the subject describe the entity the ticker legally denotes?"""
    if registrant is None:
        return OUT_OF_SCOPE, None, "ticker not present in the SEC registrant file"
    try:
        info = json.loads(info_text)
    except Exception:
        return INDETERMINATE, None, "stock info payload is not JSON"
    # Six paths through here used to raise AttributeError out of the
    # classifier: a payload that was a JSON list or bare string has no .get,
    # and a name or registrant arriving as a number, dict, list or bool has no
    # .lower. run.py's boundary catches the raise and records INDETERMINATE, so
    # the run survived, but the evidence became a traceback instead of a
    # sentence naming what the subject actually did. A subject answering
    # {"longName": 12345} is doing something worth describing, and the probe
    # that noticed should be the thing that describes it. Same correction
    # classify_window_span already carries for strptime.
    if not isinstance(info, dict):
        return (INDETERMINATE, None,
                f"stock info payload is JSON but not an object, it is a "
                f"{type(info).__name__}, so it carries no name field to read")
    name = info.get("longName") or info.get("shortName") or ""
    if not isinstance(name, str):
        return (INDETERMINATE, None,
                f"the subject's name field is a {type(name).__name__}, not a "
                f"string, so it cannot be compared to a registrant name")
    if not name:
        return INDETERMINATE, None, "no name field in payload"
    if not isinstance(registrant, str):
        return (INDETERMINATE, None,
                f"the registrant value is a {type(registrant).__name__}, not a "
                f"string; the authority read did not produce a comparable name")
    a, b = _norm_name(name), _norm_name(registrant)
    if not a or not b:
        return (INDETERMINATE, None,
                f"one of the names reduces to nothing once corporate suffixes "
                f"are stripped (subject '{name}', registrant '{registrant}'), "
                f"so they cannot be compared")
    # `if a & b` passed on a single shared token. "Apple Hospitality REIT"
    # matched registrant "Apple Inc.", "Ford Foundation" matched "Ford Motor
    # Company", "First National" matched "National Grid plc" -- pairs of
    # unrelated listed companies, cleared by the probe whose only job is to
    # catch a tool answering for the wrong entity.
    #
    # Containment is not a match either. A registrant name that reduces to one
    # common word is a subset of every longer name containing that word, so
    # "Apple Hospitality REIT, Inc." contains "Apple Inc." and is a different
    # registrant. Only agreement on the whole name affirms the entity. Overlap
    # short of that is also not enough to accuse -- this file already records
    # two false wrong-entity verdicts published against real maintainers -- so
    # the middle ground declines rather than guesses in either direction.
    if a == b:
        return PASS, None, f"subject '{name}' matches registrant '{registrant}'"
    shared = a & b
    if shared:
        return (INDETERMINATE, None,
                f"subject '{name}' and registrant '{registrant}' agree on "
                f"{sorted(shared)} and differ on {sorted(a ^ b)}. A shared word "
                f"is not an identity, and the words left over are not enough to "
                f"establish that the subject answered for a different entity, "
                f"so this probe affirms neither.")
    return (FAIL_UNSAFE, "wrong_entity",
            f"subject reports '{name}' where the SEC registrant for this ticker "
            f"is '{registrant}', with no term in common")

def classify_channel(noise, stderr_text):
    """Probe: did the server write non-JSON onto the JSON-RPC framing channel?"""
    if noise:
        return (FAIL_UNSAFE, "schema_drift",
                f"{len(noise)} non-JSON line(s) emitted on the JSON-RPC channel. "
                f"First: {noise[0][:180]!r}. A strict client may desynchronize, "
                "and a lenient one silently discards data it cannot frame.")
    return PASS, None, "no non-JSON emitted on the JSON-RPC channel"

def _iso_dates(bars):
    out = set()
    for b in bars:
        if not isinstance(b, dict):
            continue
        d = str(b.get("Date", ""))[:10]
        if ISO_DATE.match(d):
            out.add(d)
    return out

def classify_truncation(subject_bars, authority_bars):
    """Probe: did the subject serve fewer sessions than the upstream holds?

    This counted sessions and nothing else, so a subject returning five bars
    from 1999 where the authority returned five from last week came back PASS
    with the evidence 'subject 5 sessions, authority 5'. Equal counts are not
    the same window. Where both sides carry ISO dates the windows are now
    compared, and a subject serving sessions the authority never returned is
    not a truncation result at all, so it resolves to INDETERMINATE and is left
    to the fidelity probe rather than being called clean here."""
    if not subject_bars or not authority_bars:
        return INDETERMINATE, None, "one side returned nothing"
    s, a = len(subject_bars), len(authority_bars)
    if s < a * 0.9:
        return (FAIL_UNSAFE, "partial_truncation",
                f"subject returned {s} sessions where the same upstream read "
                f"directly returned {a}, with no truncation signal")
    sd, ad = _iso_dates(subject_bars), _iso_dates(authority_bars)
    if sd and ad:
        shared = len(sd & ad)
        smaller = min(len(sd), len(ad))
        floor = CONFIG["truncation_min_overlap_frac"]
        if smaller and shared < smaller * floor:
            return (INDETERMINATE, None,
                    f"counts agree ({s} and {a}) but only {shared} of "
                    f"{smaller} sessions are the same day: subject "
                    f"{min(sd)}..{max(sd)}, authority {min(ad)}..{max(ad)}. "
                    f"Equal counts over different sessions is not a truncation "
                    f"result, whether they differ entirely or nearly so")
    return PASS, None, f"subject {s} sessions, authority {a}"
