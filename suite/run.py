#!/usr/bin/env python3
"""
Nobulex reliability suite v0.1 -- runner.

Drives a live MCP subject over stdio, executes every probe, classifies each
observation with the pure classifiers in harness.py, and writes a record.

Usage:
  python3 run.py --subject-dir /path/to/server-repo \\
                 --entry server.py \\
                 --python /path/to/python3 \\
                 --out ../records/

Every probe is wrapped. An unexpected exception becomes INDETERMINATE with the
traceback attached to the record. Nothing in here can produce a PASS by
falling through.
"""

import argparse, hashlib, json, os, platform, subprocess, sys, traceback
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import (
    SUITE_VERSION, SCHEMA_VERSION, CONFIG, MCPStdio, aggregate, parse_bars,
    a1_chart, a2_edgar, AuthorityUnavailable,
    PASS, FAIL_SAFE, FAIL_UNSAFE, INDETERMINATE, OUT_OF_SCOPE,
    classify_absent_entity, classify_empty_window, classify_invalid_argument,
    classify_window_span,
    classify_fidelity, classify_ohlc, classify_monotonic, classify_freshness,
    classify_entity, classify_channel, classify_truncation,
)

VALIDITY_DAYS = 7
LIVE_TICKER = "AAPL"
ABSENT_TICKER = "ZZZZQQ"


class SubjectDidNotStart(Exception):
    """Control flow only. A subject that never completes initialize cannot be
    probed as a tool, but the run still has to produce a record, because a
    crash with no record is indistinguishable from a run that was never made."""


def resolved_deps(python_exe):
    """The declared dependencies are floating ranges. What actually ran is the
    resolved set, and a record that omits it is not reproducible.

    pip is not guaranteed to be present: environments built by uv routinely
    omit it. The resolved set is a property of the environment rather than of
    pip, so when pip is missing this reads the installed distributions directly
    instead of returning nothing. Reporting null here would strip the pinned
    configuration of the exact detail it exists to record."""
    try:
        out = subprocess.run([python_exe, "-m", "pip", "freeze"],
                             capture_output=True, text=True, timeout=60).stdout
        deps = sorted(l.strip() for l in out.splitlines() if l.strip()
                      and not l.startswith("-"))
        if deps:
            return deps
    except Exception:
        pass
    probe = ("import json\n"
             "from importlib.metadata import distributions\n"
             "print(json.dumps(sorted({(d.metadata['Name'] or '?') + '==' + "
             "(d.version or '?') for d in distributions()})))")
    try:
        out = subprocess.run([python_exe, "-c", probe],
                             capture_output=True, text=True, timeout=60)
        return json.loads(out.stdout)
    except Exception:
        return None


def auth_failure(exc):
    """Turn an authority read failure into checkable fields.

    A reader has to be able to tell an upstream that refused this harness apart
    from a machine that had no route out, because only the first says anything
    about the authority and neither says anything about the subject. When the
    failure did not come through the authority reader at all, the type name is
    still better than nothing, and it is labelled as unstructured so nobody
    mistakes it for a status."""
    if isinstance(exc, AuthorityUnavailable):
        return {"failure": exc.as_dict()}
    return {"failure": {"url": None, "http_status": None,
                        "reason": f"{type(exc).__name__}: {exc}",
                        "body_excerpt": None, "attempts": None,
                        "unstructured": True}}


LOCKFILE_NAMES = ("uv.lock", "poetry.lock", "requirements.txt",
                  "requirements.lock", "Pipfile.lock", "pdm.lock")


def lockfiles(subject_dir):
    """A repository can declare floating ranges in its manifest and also ship a
    lockfile that pins something entirely different. Those are two
    configurations, not one, they resolve differently, and they can earn
    opposite verdicts. The record names which path was installed and carries a
    digest of every lockfile in the tree, so a reader can check that claim
    instead of taking it."""
    found = {}
    for name in LOCKFILE_NAMES:
        p = os.path.join(subject_dir, name)
        if os.path.exists(p):
            try:
                with open(p, "rb") as fh:
                    found[name] = hashlib.sha256(fh.read()).hexdigest()
            except Exception:
                found[name] = None
    return found


def git(subject_dir, *args):
    try:
        return subprocess.run(["git"] + list(args), cwd=subject_dir,
                              capture_output=True, text=True,
                              timeout=20).stdout.strip()
    except Exception:
        return ""


class Run:
    def __init__(self):
        self.probes = []

    def record(self, probe_id, description, outcome, cause, detail,
               request=None, response=None, error=None):
        self.probes.append({
            "probe": probe_id,
            "description": description,
            "outcome": outcome,
            "loss_cause": cause,
            "detail": detail,
            "request": request,
            "response_excerpt": (response or "")[:900] if response else None,
            "harness_error": error,
        })
        cause_s = f" / {cause}" if cause else ""
        print(f"  {outcome:<14}{cause_s:<22} {probe_id}")
        print(f"      {detail}")

    def guard(self, probe_id, description, fn, request=None):
        """Any exception inside a probe is a harness fault, not a subject
        verdict. It resolves INDETERMINATE, never PASS."""
        try:
            outcome, cause, detail, response = fn()
            self.record(probe_id, description, outcome, cause, detail,
                        request, response)
        except Exception:
            tb = traceback.format_exc()
            self.record(probe_id, description, INDETERMINATE, None,
                        "harness fault during probe execution", request,
                        None, tb)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--subject-dir", required=True)
    ap.add_argument("--entry", default="server.py")
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--out", default="records")
    ap.add_argument("--record-id", default=None)
    ap.add_argument("--install-path", default="unspecified",
                    help="How the subject's environment was built: "
                         "'declared-ranges' to install from the manifest's own "
                         "version specifiers, 'shipped-lock' to install from a "
                         "lockfile committed to the repository. A repository "
                         "can ship both. They are different configurations and "
                         "may earn different verdicts.")
    args = ap.parse_args()

    # The subject server is launched with cwd set to its own repository, so a
    # relative interpreter path stops resolving the moment the process starts.
    # Resolve it here, against the directory the operator actually typed it in,
    # rather than letting it fail inside Popen with a path nobody recognises.
    args.python = os.path.abspath(args.python)

    started = datetime.now(timezone.utc)
    subject_dir = os.path.abspath(args.subject_dir)

    commit = git(subject_dir, "rev-parse", "HEAD")
    commit_date = git(subject_dir, "show", "-s", "--format=%cI", "HEAD")
    dirty = bool(git(subject_dir, "status", "--porcelain"))
    origin = git(subject_dir, "config", "--get", "remote.origin.url")

    declared_deps = None
    try:
        import re as _re
        pt = open(os.path.join(subject_dir, "pyproject.toml")).read()
        m = _re.search(r"dependencies\s*=\s*\[(.*?)\]", pt, _re.S)
        if m:
            declared_deps = _re.findall(r'"([^"]+)"', m.group(1))
    except Exception:
        pass

    print(f"\nNobulex {SUITE_VERSION}")
    print(f"subject   {os.path.basename(subject_dir)} @ {commit[:7] or '?'}"
          f"{'  [WORKING TREE DIRTY]' if dirty else ''}")
    print(f"started   {started.isoformat()}\n")

    if dirty:
        print("  refusing to issue a verdict: the working tree is modified, so "
              "the commit SHA does not describe what actually ran.\n")

    r = Run()

    # ------------------------------------------------------- authorities
    auth_status = {}
    a1 = a2 = None
    try:
        a1 = a1_chart(LIVE_TICKER, rng="1mo", interval="1d")
        auth_status["A1"] = {"reachable": True, "bars": len(a1["bars"]),
                             "symbol": a1["symbol"],
                             "date_basis": a1["tz_basis"]}
        print(f"  authority A1  {len(a1['bars'])} sessions, "
              f"date basis: {a1['tz_basis']}")
    except Exception as e:
        auth_status["A1"] = {"reachable": False, **auth_failure(e)}
        print(f"  authority A1  UNREACHABLE {e}")
    try:
        a2 = a2_edgar(LIVE_TICKER)
        auth_status["A2"] = {"reachable": True, "registrant": a2}
        print(f"  authority A2  registrant for {LIVE_TICKER}: {a2}")
    except Exception as e:
        auth_status["A2"] = {"reachable": False, **auth_failure(e)}
        print(f"  authority A2  UNREACHABLE {e}")
    print()

    # ------------------------------------------------------------ subject
    cmd = [args.python, args.entry]
    client = MCPStdio(cmd, cwd=subject_dir)
    server_info, tool_names, stderr_text = {}, [], ""
    attestation = "TOOL"
    started_ok = False

    try:
        try:
            init = client.initialize()
            server_info = init.get("result", {}).get("serverInfo", {})
            listed = client.request("tools/list")
            tool_names = [t["name"] for t in
                          listed.get("result", {}).get("tools", [])]
            started_ok = True
            # Labelled as serverInfo on purpose. This is the name and version
            # the server reports for ITSELF over MCP, which is not the version
            # of the package it wraps and must never be read as one. A server
            # is free to answer here with the version of its MCP library while
            # its lockfile pins a different major version of the data package
            # it actually calls. The record stores both, separately, and a
            # reader who confuses them has been misled by this line, not by
            # the record.
            print(f"  serverInfo (self-reported) "
                  f"{server_info.get('name','?')}/"
                  f"{server_info.get('version','?')}, {len(tool_names)} tools\n")
        except Exception as e:
            # A subject that will not start has not been measured as a tool, so
            # this cannot be issued as a TOOL attestation. What has been measured
            # is whether the package still composes with the dependency set its
            # own manifest resolves to, which is a COMPATIBILITY question, and
            # the record says so rather than quietly reusing the wrong type.
            #
            # The verdict is FAIL_SAFE, not FAIL_UNSAFE. The process dies before
            # it can answer anything, so no caller can mistake the result for
            # data. That is the failure mode this registry wants tools to have.
            attestation = "COMPATIBILITY"
            # Close now rather than in the finally block, so the probe carries
            # the subject's own account of why it died and not just the
            # harness's view from the outside.
            client.close()
            last = [l for l in client.stderr_text.splitlines() if l.strip()]
            r.record("P00", "subject starts and completes MCP initialize",
                     FAIL_SAFE, None,
                     f"the subject never completed initialize ({e!r}); it "
                     f"{client.exit_summary()}"
                     + (f", last stderr line: {last[-1].strip()!r}" if last
                        else "")
                     + ". It is unusable in this environment, and it stops at "
                       "startup rather than returning data an agent could act "
                       "on",
                     {"argv": cmd, "cwd": subject_dir},
                     client.stderr_text[-900:] or None)
            print(f"  server    DID NOT START  {e!r}")
            print(f"            {client.exit_summary()}")
            if last:
                print(f"            {last[-1].strip()[:150]}\n")
            raise SubjectDidNotStart()

        r.record("P00", "subject starts and completes MCP initialize",
                 PASS, None,
                 f"initialize and tools/list both answered, {len(tool_names)} "
                 "tools exposed", {"argv": cmd, "cwd": subject_dir}, None)

        hist = "get_historical_stock_prices"

        # P01 nonexistent entity ------------------------------------------
        def p01():
            req = {"ticker": ABSENT_TICKER, "period": "5d", "interval": "1d"}
            text, is_err, _ = client.call(hist, req)
            parsed, _ = parse_bars(text)
            o, c, d = classify_absent_entity(text, is_err, parsed)
            return o, c, d, text
        r.guard("P01", "nonexistent ticker", p01,
                {"tool": "get_historical_stock_prices", "ticker": ABSENT_TICKER})

        # P02 invalid interval --------------------------------------------
        def p02():
            req = {"ticker": LIVE_TICKER, "period": "5d", "interval": "7q"}
            text, is_err, _ = client.call(hist, req)
            parsed, _ = parse_bars(text)
            o, c, d = classify_invalid_argument(text, is_err, parsed,
                                                "interval='7q'")
            return o, c, d, text
        r.guard("P02", "interval outside the documented enumeration", p02,
                {"tool": hist, "interval": "7q"})

        # P03 oversized window --------------------------------------------
        def p03():
            # This probe has been wrong twice, and both times in the direction
            # that matters: it accused a real maintainer of a substitution that
            # never happened. Version one asked for period='13y' and read any
            # returned data as a silent fallback; the subject serves exactly
            # thirteen years for '13y'. Version two asked for '99y', measured
            # 46% of the request, and called that a cap; 1980-12-12 is the day
            # AAPL listed, so 46% was every bar in existence.
            #
            # A shortfall means nothing on its own. So the control is measured
            # first: period='max' is documented, and it is the subject's own
            # statement of how far back it can reach. Only a '99y' window
            # SHORTER than what the subject itself serves under 'max' is a
            # finding, and then the subject has contradicted itself in writing.
            ctl_text, ctl_err, _ = client.call(
                hist, {"ticker": LIVE_TICKER, "period": "max",
                       "interval": "1d"})
            ctl_bars, _ = parse_bars(ctl_text)
            available = None
            if isinstance(ctl_bars, list) and len(ctl_bars) >= 2 and not ctl_err:
                cd = sorted(str(b.get("Date", ""))[:10] for b in ctl_bars
                            if isinstance(b, dict) and b.get("Date"))
                if len(cd) >= 2:
                    available = (datetime.strptime(cd[-1], "%Y-%m-%d")
                                 - datetime.strptime(cd[0], "%Y-%m-%d")).days

            req = {"ticker": LIVE_TICKER, "period": "99y", "interval": "1d"}
            text, is_err, _ = client.call(hist, req)
            parsed, _ = parse_bars(text)
            o, c, d = classify_window_span(text, is_err, parsed,
                                           requested_days=99 * 365,
                                           arg_desc="period='99y'",
                                           available_days=available)
            return o, c, d, text
        r.guard("P03", "oversized window against the subject's own maximum",
                p03, {"tool": hist, "period": "99y",
                      "requested_days": 99 * 365,
                      "control": "period='max' on the same entity"})

        def p11():
            # A stray trailing space is what a period actually looks like when
            # it arrives from a config file, an environment variable, or a
            # spreadsheet cell. If ' 1mo ' and '1mo' disagree, the disagreement
            # should be audible.
            req = {"ticker": LIVE_TICKER, "period": "1mo ", "interval": "1d"}
            text, is_err, _ = client.call(hist, req)
            parsed, _ = parse_bars(text)
            o, c, d = classify_invalid_argument(text, is_err, parsed,
                                                "period='1mo ' (trailing space)")
            return o, c, d, text
        r.guard("P11", "whitespace-padded argument from a config source", p11,
                {"tool": hist, "period": "1mo "})

        # live pull, reused by P04 through P08 ------------------------------
        live_text, live_bars = None, None
        try:
            live_text, _le, _ = client.call(
                hist, {"ticker": LIVE_TICKER, "period": "1mo",
                       "interval": "1d"})
            live_bars, _ = parse_bars(live_text)
        except Exception:
            pass

        def p04():
            o, c, d = classify_ohlc(live_bars)
            return o, c, d, live_text
        r.guard("P04", "OHLC internal consistency", p04,
                {"tool": hist, "ticker": LIVE_TICKER, "period": "1mo"})

        def p05():
            o, c, d = classify_monotonic(live_bars)
            return o, c, d, None
        r.guard("P05", "session dates strictly increasing", p05)

        def p06():
            o, c, d = classify_freshness(
                live_bars, datetime.now(timezone.utc),
                CONFIG["freshness_max_calendar_days"])
            return o, c, d, None
        r.guard("P06", "most recent session inside the freshness bound", p06)

        def a1_missing():
            """The subject is not the reason this probe has no answer, and the
            record has to say so in terms a reader can check rather than in the
            single word 'unreachable'."""
            f = auth_status.get("A1", {}).get("failure", {}) or {}
            st, att = f.get("http_status"), f.get("attempts")
            return (INDETERMINATE, None,
                    "authority A1 did not answer"
                    + (f", HTTP {st}" if st else f", {f.get('reason')}")
                    + (f", after {att} attempts" if att else "")
                    + ". No comparison was performed, so no claim is issued "
                      "about the subject in either direction. This is a "
                      "property of the authority and of the network the run "
                      "was made from, not evidence about the subject.", None)

        def p07():
            if not a1:
                return a1_missing()
            o, c, d = classify_fidelity(live_bars, a1["bars"],
                                        CONFIG["price_tolerance_rel"])
            return o, c, d, None
        r.guard("P07", "transport fidelity against authority A1", p07)

        def p08():
            if not a1:
                return a1_missing()
            o, c, d = classify_truncation(live_bars, a1["bars"])
            return o, c, d, None
        r.guard("P08", "silent truncation against authority A1", p08)

        # P09 entity identity ----------------------------------------------
        def p09():
            text, is_err, _ = client.call("get_stock_info",
                                          {"ticker": LIVE_TICKER})
            if a2 is None and auth_status.get("A2", {}).get("reachable"):
                return (OUT_OF_SCOPE, None,
                        "ticker not present in the SEC registrant file", text)
            if not auth_status.get("A2", {}).get("reachable"):
                return (INDETERMINATE, None,
                        "authority A2 unreachable, entity unverifiable", text)
            o, c, d = classify_entity(text, a2)
            return o, c, d, text
        r.guard("P09", "entity identity against authority A2", p09,
                {"tool": "get_stock_info", "ticker": LIVE_TICKER})

    except SubjectDidNotStart:
        pass
    finally:
        stderr_text = client.close() or ""

    # P10 protocol channel hygiene -------------------------------------
    if started_ok:
        o, c, d = classify_channel(client.protocol_noise, stderr_text)
        r.record("P10", "JSON-RPC channel carries only JSON-RPC", o, c, d,
                 None, "\n".join(client.protocol_noise)[:900] or None)
    else:
        # A server that died at import emitted nothing at all, and "nothing" is
        # not a clean channel. Recording PASS here would be a verdict about a
        # measurement that was never taken.
        r.record("P10", "JSON-RPC channel carries only JSON-RPC",
                 OUT_OF_SCOPE, None,
                 "the subject never opened the channel, so its hygiene was not "
                 "observed", None, None)

    # ---------------------------------------------------------- aggregate
    outcomes = [p["outcome"] for p in r.probes]
    verdict = aggregate(outcomes)
    if dirty or not commit:
        verdict = INDETERMINATE

    ended = datetime.now(timezone.utc)
    causes = sorted({p["loss_cause"] for p in r.probes if p["loss_cause"]})

    rec = {
        "schema": SCHEMA_VERSION,
        "record_id": args.record_id or f"NBLX-{ended.strftime('%Y%m%d')}-002",
        "attestation_type": attestation,
        "verdict": verdict,
        "loss_causes": causes,
        "subject": {
            "package": os.path.basename(subject_dir),
            "commit": commit or None,
            "commit_date": commit_date or None,
            "origin": origin or None,
            "working_tree_clean": not dirty,
            "entrypoint": args.entry,
            "configuration": {"transport": "stdio",
                              "protocol_version": "2024-11-05",
                              "install_path": args.install_path,
                              "lockfiles_present": lockfiles(subject_dir),
                              "server_info": server_info,
                              "tools_exposed": tool_names},
            "upstream": "Yahoo Finance, via the yfinance package",
            "execution_environment": {
                "harness_python": platform.python_version(),
                "subject_interpreter": args.python,
                "platform": platform.platform(),
                "machine": platform.machine(),
                "declared_dependencies": declared_deps,
                "resolved_dependencies": resolved_deps(args.python),
            },
            "suite": SUITE_VERSION,
            "observed_at": started.isoformat(),
        },
        "validity": {
            "from": started.isoformat(),
            "until": (started + timedelta(days=VALIDITY_DAYS)).isoformat(),
            "note": "Queried outside this window the record returns EXPIRED "
                    "regardless of verdict.",
        },
        "authorities": {k: dict(CONFIG["authorities"][k], **auth_status.get(k, {}))
                        for k in CONFIG["authorities"]},
        "pinned_config": {k: v for k, v in CONFIG.items() if k != "authorities"},
        "probes": r.probes,
        "server_stderr_excerpt": (stderr_text or "")[-1500:] or None,
        "subject_process": {"exit_code": client.returncode,
                            "how_it_ended": client.exit_summary()},
        "run_duration_s": round((ended - started).total_seconds(), 2),
        "warranty": "This record describes the behavior of the stated subject "
                    "tuple under the stated conditions at the stated time. It "
                    "makes no claim about safety, fitness for any purpose, the "
                    "maintainer, or behavior on any other commit, "
                    "configuration, or upstream.",
    }

    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, f"{rec['record_id']}.json")
    with open(path, "w") as fh:
        json.dump(rec, fh, indent=2)

    print(f"\n{'='*66}")
    print(f"VERDICT   {verdict}   ({attestation})")
    if causes:
        print(f"causes    {', '.join(causes)}")
    print(f"probes    " + "  ".join(
        f"{o}:{outcomes.count(o)}" for o in
        [FAIL_UNSAFE, FAIL_SAFE, INDETERMINATE, PASS, OUT_OF_SCOPE]
        if outcomes.count(o)))
    print(f"record    {path}")
    print(f"{'='*66}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
