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

import argparse, hashlib, json, os, platform, re, subprocess, sys, traceback
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import (
    SUITE_VERSION, SCHEMA_VERSION, CONFIG, MCPStdio, aggregate, parse_bars,
    next_in_sequence,
    a1_chart, a2_edgar, AuthorityUnavailable,
    PASS, FAIL_SAFE, FAIL_UNSAFE, INDETERMINATE, OUT_OF_SCOPE,
    classify_absent_entity, classify_empty_window, classify_invalid_argument,
    classify_padded_argument,
    classify_window_span,
    classify_fidelity, classify_ohlc, classify_monotonic, classify_freshness,
    classify_entity, classify_channel, classify_truncation,
)

VALIDITY_DAYS = 7
LIVE_TICKER = "AAPL"
ABSENT_TICKER = "ZZZZQQ"

# Any verdict that gets HELD behind right of reply (see the publication block
# below and hold.py) is gated by a process that itself takes up to seven days
# to even begin: nothing here starts that clock, a person has to deliver the
# artifact. A validity window computed from the moment of observation runs
# out before the reply process has a chance to start, let alone finish.
# Records already held in this registry did exactly this: they reached their
# validity deadline while still sitting at artifact_delivered_at=null,
# which is to say before their subject had been written to. This set must
# match the HELD condition in the publication block, not just the two FAIL
# verdicts: INDETERMINATE is held too, and a mismatch here would leave
# INDETERMINATE records with the same self-defeating deadline. For a held
# verdict, this leaves "until" unset rather than issuing a deadline the
# record cannot possibly meet. The clock starts once
# publication.right_of_reply.window_closes_at exists.
REQUIRES_REPLY = {FAIL_SAFE, FAIL_UNSAFE, INDETERMINATE}


def _validity_block(started, verdict):
    if verdict not in REQUIRES_REPLY:
        return {
            "from": started.isoformat(),
            "until": (started + timedelta(days=VALIDITY_DAYS)).isoformat(),
            "note": "Queried outside this window the record returns EXPIRED "
                    "regardless of verdict.",
        }
    return {
        "from": started.isoformat(),
        "until": None,
        "note": "This verdict is adverse and gated by right of reply. The "
                f"{VALIDITY_DAYS}-day validity window has not started: "
                "starting it at observation time instead of disclosure time "
                "let earlier records expire before their reply window had "
                "opened. This record's window starts when "
                "publication.right_of_reply.window_closes_at is set.",
    }


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


ORIGIN_REPO = re.compile(r"[/:]([^/:]+?)(?:\.git)?/?$")


def repo_from_origin(origin):
    """The repository name in a git remote URL, or None if there isn't one."""
    if not isinstance(origin, str) or not origin.strip():
        return None
    m = ORIGIN_REPO.search(origin.strip())
    if not m:
        return None
    name = m.group(1).strip()
    return name or None


def package_name(subject_dir, origin):
    """What to call the subject in its own record.

    This was os.path.basename(subject_dir), which is not the subject's identity
    and is not read from the environment either. It is whatever the operator
    named the folder. Clone the same commit into ~/tmp and the record says the
    package is "tmp", and the renderer's held-subject guard then searches for
    "tmp" while the page is free to print the real name. The origin catches
    that case, so it was never a leak, but the record named the wrong thing and
    the record is the evidence.

    The remote URL is read off the clone by git, so it is environment-derived
    in the way the directory name only appears to be, and a stranger can check
    it against the repository. Falls back to the directory name when there is
    no remote, and the record says which of the two it used rather than leaving
    a reader to guess.
    """
    return repo_from_origin(origin) or os.path.basename(subject_dir)


def next_record_id(out_dir, day):
    """Every record id already under out_dir, handed to the pure sequencer.

    A default computed from the date alone is wrong by construction, since the
    sequence is global and the date is not, and a default that is a string
    literal is wrong the second time it runs. This reads what is on disk
    instead. Held and withdrawn records sit in a subdirectory, so it walks
    rather than lists, and it reads no register but the one it was pointed at:
    an empty directory yields 001, which is what a stranger's first run should
    produce.
    """
    names = []
    for _root, _dirs, files in os.walk(out_dir):
        names.extend(files)
    return next_in_sequence(names, day)


def live_pull_note(text, is_error, bars, parse_note, raised=None):
    """Why the shared live response cannot be read, or None if it can.

    P04 through P08 all read one response. When that response was unusable
    each of them reported "no bars", which is a statement that the subject
    returned nothing. It could equally have been the subject refusing through
    the protocol error channel, the call raising inside the harness, or a
    payload that is JSON but not the documented record array. Those are
    different facts about different parties, and one of them is not about the
    subject at all. Collapsing them into two words is the same defect this
    suite grades other people for, and the same one this file already avoids
    on the authority side through a1_missing().

    Pure, and takes the pieces rather than the client, so the selftest can
    drive every branch without a subject.
    """
    if raised is not None:
        return ("the shared live request raised inside the harness: %s. That "
                "is a fact about this run, not about the subject" % raised)
    if is_error:
        return ("the subject refused the shared live request through the "
                "protocol error channel")
    if parse_note:
        return ("the shared live request returned a payload that is not the "
                "documented record array: %s" % parse_note)
    if not isinstance(bars, list):
        return "the shared live request returned no readable record array"
    if not bars:
        return "the shared live request returned an empty record array"
    return None


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
    ap.add_argument("--record-id", default=None,
                    help="The id this record will be filed under. Defaults to "
                         "one past the highest number already present under "
                         "--out, counting held and withdrawn records, since a "
                         "withdrawn record still spent its number. A run whose "
                         "id is already taken is refused before it starts "
                         "rather than allowed to overwrite the record on disk.")
    ap.add_argument("--tool-history", default=None,
                    help="The subject's tool that returns historical price "
                         "bars, named exactly as it appears in tools/list. "
                         "Required, and checked against the subject's own tool "
                         "list before any probe runs. Run without it once and "
                         "the harness prints what this subject exposes.")
    ap.add_argument("--tool-info", default=None,
                    help="The subject's tool that returns entity metadata for "
                         "a ticker, named exactly as it appears in tools/list. "
                         "Required, on the same grounds as --tool-history.")
    ap.add_argument("--install-path", default="unspecified",
                    help="How the subject's environment was built: "
                         "'declared-ranges' to install from the manifest's own "
                         "version specifiers, 'shipped-lock' to install from a "
                         "lockfile committed to the repository. A repository "
                         "can ship both. They are different configurations and "
                         "may earn different verdicts.")
    ap.add_argument("--upstream", required=True,
                    help="The data source the subject ultimately reads from, "
                         "named by the operator. Required, and deliberately "
                         "without a default. Every other field of the subject "
                         "tuple is derived from the run: the package from the "
                         "directory, the commit from git, the dependencies "
                         "from the interpreter that was used. This one cannot "
                         "be derived, because a server does not have to say "
                         "where its data comes from and can be wrong when it "
                         "does. A default here would be a value the record "
                         "asserts and nobody observed, which is fabricated_"
                         "field, which is a cause this suite grades other "
                         "software for.")
    args = ap.parse_args()

    # The subject server is launched with cwd set to its own repository, so a
    # relative interpreter path stops resolving the moment the process starts.
    # Resolve it here, against the directory the operator actually typed it in,
    # rather than letting it fail inside Popen with a path nobody recognises.
    args.python = os.path.abspath(args.python)

    started = datetime.now(timezone.utc)
    subject_dir = os.path.abspath(args.subject_dir)

    # Settled before the first probe, not after the last one. An operator who
    # has named a number that is already taken should learn that in the first
    # second, not at the end of a live run they now have to repeat. The date
    # comes from the start of the observation, so a run that crosses midnight
    # is filed under the day it watched rather than the day it finished.
    record_id = args.record_id or next_record_id(
        args.out, started.strftime("%Y%m%d"))
    out_path = os.path.join(os.path.abspath(args.out), f"{record_id}.json")
    if os.path.exists(out_path):
        print(f"refusing to run: {out_path} already exists.\n"
              "A record id is an identity in a register, and other documents "
              "cite it. Overwriting one would destroy evidence while leaving "
              "every reference to it intact, which is the exact shape of "
              "failure this suite exists to catch. Pass --record-id with an "
              "unused id, or write to a different --out.", file=sys.stderr)
        return 2

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
        print("  the working tree is modified, so the commit SHA does not "
              "describe what actually ran. The verdict for this run is forced "
              "to INDETERMINATE and the record will carry "
              "working_tree_clean: false.\n")

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

        # Every probe below calls the subject by tool name, and a name the
        # subject does not expose comes back as a protocol error. A protocol
        # error is what several of these probes count as CORRECT behavior: a
        # tool that refuses a nonexistent ticker through the error channel has
        # passed P01 by design. So a run pointed at a subject without these
        # tools would answer PASS on evidence consisting entirely of the tools
        # not being there, and the record would carry a full subject tuple and
        # look exactly like a real one. That is a verdict that fails quiet,
        # produced by the suite whose only purpose is to catch verdicts that
        # fail quiet. The names are operator supplied and checked against the
        # subject's own tools/list before a single probe runs, so that every
        # error a classifier later sees is the subject refusing a question it
        # was actually asked.
        named = {"--tool-history": args.tool_history,
                 "--tool-info": args.tool_info}
        bad = [f"{flag} {name!r} is not exposed" if name
               else f"{flag} was not given" for flag, name in named.items()
               if name not in tool_names]
        if bad:
            print("\nrefusing to probe: " + "; ".join(bad) + ".\n"
                  "This suite calls the subject by tool name, and a name that "
                  "is not there answers every probe with a protocol error, "
                  "which several probes count as correct behavior. The run "
                  "would return PASS on the strength of the tool being "
                  "absent. Name the tools explicitly.\n"
                  "This subject exposes: "
                  + (", ".join(tool_names) or "(no tools at all)"),
                  file=sys.stderr)
            return 2

        hist = args.tool_history
        info = args.tool_info

        # P01 nonexistent entity ------------------------------------------
        def p01():
            req = {"ticker": ABSENT_TICKER, "period": "5d", "interval": "1d"}
            text, is_err, _ = client.call(hist, req)
            parsed, _ = parse_bars(text)
            o, c, d = classify_absent_entity(text, is_err, parsed)
            return o, c, d, text
        r.guard("P01", "nonexistent ticker", p01,
                {"tool": hist, "ticker": ABSENT_TICKER})

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
            #
            # That is what this always said and it is not what it did. The
            # padded call went to classify_invalid_argument, whose contract is
            # that the presence of data is itself the evidence, and that
            # contract holds only for an argument no reading can honor.
            # Whitespace has an obvious reading. A tool that strips it and
            # serves one month is correct, and it was being graded
            # FAIL_UNSAFE unsignaled_fallback for it.
            #
            # The control the comment implied is now actually fetched, on the
            # same pattern P03 uses, so the finding rests on an observed
            # difference between the two responses rather than on the mere
            # existence of one.
            padded_text, padded_err, _ = client.call(
                hist, {"ticker": LIVE_TICKER, "period": "1mo ",
                       "interval": "1d"})
            padded_bars, _ = parse_bars(padded_text)
            base_text, base_err, _ = client.call(
                hist, {"ticker": LIVE_TICKER, "period": "1mo",
                       "interval": "1d"})
            base_bars, _ = parse_bars(base_text)
            o, c, d = classify_padded_argument(
                padded_text, padded_err, padded_bars,
                base_text, base_err, base_bars,
                "period='1mo ' (trailing space)")
            return o, c, d, padded_text
        r.guard("P11", "whitespace-padded argument against its unpadded "
                       "control", p11,
                {"tool": hist, "period": "1mo ",
                 "control": "period='1mo' on the same entity"})

        # live pull, reused by P04 through P08 ------------------------------
        # The failure used to be swallowed whole: `except Exception: pass`,
        # the isError flag dropped on the floor, and parse_bars' own note
        # discarded. Five probes then reported "no bars" over a response that
        # may never have been read at all.
        live_text, live_bars, live_note = None, None, None
        try:
            live_text, live_err, _ = client.call(
                hist, {"ticker": LIVE_TICKER, "period": "1mo",
                       "interval": "1d"})
            live_bars, parse_note = parse_bars(live_text)
            live_note = live_pull_note(live_text, live_err, live_bars,
                                       parse_note)
        except Exception as exc:
            live_note = live_pull_note(
                None, False, None, None,
                raised="%s: %s" % (type(exc).__name__, str(exc)[:160]))
        if live_note:
            live_bars = None

        def live_missing():
            """Why P04 through P08 have nothing to read, in terms a reader can
            check, rather than in the two words 'no bars'."""
            return (INDETERMINATE, None,
                    live_note + ". P04 through P08 all read that one response, "
                    "so none of them observed the subject's data and none "
                    "issues a claim about it in either direction.", live_text)

        def p04():
            if live_note:
                return live_missing()
            o, c, d = classify_ohlc(live_bars)
            return o, c, d, live_text
        r.guard("P04", "OHLC internal consistency", p04,
                {"tool": hist, "ticker": LIVE_TICKER, "period": "1mo"})

        def p05():
            if live_note:
                return live_missing()
            o, c, d = classify_monotonic(live_bars)
            return o, c, d, None
        r.guard("P05", "session dates strictly increasing", p05)

        def p06():
            if live_note:
                return live_missing()
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
            if live_note:
                return live_missing()
            if not a1:
                return a1_missing()
            o, c, d = classify_fidelity(live_bars, a1["bars"],
                                        CONFIG["price_tolerance_rel"])
            return o, c, d, None
        r.guard("P07", "transport fidelity against authority A1", p07)

        def p08():
            if live_note:
                return live_missing()
            if not a1:
                return a1_missing()
            o, c, d = classify_truncation(live_bars, a1["bars"])
            return o, c, d, None
        r.guard("P08", "silent truncation against authority A1", p08)

        # P09 entity identity ----------------------------------------------
        def p09():
            text, is_err, _ = client.call(info, {"ticker": LIVE_TICKER})
            if a2 is None and auth_status.get("A2", {}).get("reachable"):
                return (OUT_OF_SCOPE, None,
                        "ticker not present in the SEC registrant file", text)
            if not auth_status.get("A2", {}).get("reachable"):
                return (INDETERMINATE, None,
                        "authority A2 unreachable, entity unverifiable", text)
            o, c, d = classify_entity(text, a2)
            return o, c, d, text
        r.guard("P09", "entity identity against authority A2", p09,
                {"tool": info, "ticker": LIVE_TICKER})

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
        "record_id": record_id,
        "attestation_type": attestation,
        "verdict": verdict,
        "loss_causes": causes,
        "subject": {
            "package": package_name(subject_dir, origin),
            "package_source": "origin" if repo_from_origin(origin) else "directory",
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
            # Operator-declared, and labelled that way in the record, because
            # it is the one field of the tuple that no part of the run can
            # observe. It is not read back from the subject, since a subject
            # asserting its own upstream is the same class of evidence as a
            # subject asserting its own version, and that has already been
            # wrong once here.
            "upstream": args.upstream,
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
        "publication": {
            # An adverse verdict cannot leave this runner without declaring the gate
            # holding it. A held record whose status is unstated is the register
            # failing to say what it is withholding, which is the defect this
            # project exists to name. See suite/hold.py, which reports "unstated"
            # rather than inventing a status, and was how this gap was found.
            "status": "HELD" if verdict in (FAIL_SAFE, FAIL_UNSAFE, INDETERMINATE) else "PUBLISHABLE",
            "held_by": "right_of_reply" if verdict in (FAIL_SAFE, FAIL_UNSAFE, INDETERMINATE) else None,
            "right_of_reply": ({
                "required": True,
                "rule": "Before any record with an adverse finding is published, the "
                        "maintainer of the subject receives the full run artifact and has "
                        "seven days to respond. The reply publishes alongside the record, "
                        "unedited, and cannot alter the verdict. Only a new run under newly "
                        "pinned conditions produces a new verdict.",
                "recipient": "maintainer of " + args.upstream,
                "notice": None,
                "artifact_delivered_at": None,
                "delivery_url": None,
                "window_days": 7,
                "window_closes_at": None,
                "reply_received_at": None,
                "reply": None,
            } if verdict in (FAIL_SAFE, FAIL_UNSAFE, INDETERMINATE) else None),
        },
        "validity": _validity_block(started, verdict),
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

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    path = out_path
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
