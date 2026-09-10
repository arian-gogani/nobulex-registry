#!/usr/bin/env python3
"""Render the public register from the records, so the two cannot disagree.

WHY THIS IS A GENERATOR AND NOT AN HTML FILE
The register page was hand-written, and for one day it published a record whose
subject named commit 540267a. No such commit exists in the subject repository.
Nobody had lied; the page had simply drifted away from the evidence, which is
the exact failure this registry was built to detect in other people's software.
A page that is typed by hand can say anything. A page that is compiled from
records can only say what was measured.

So the rule is now structural rather than careful: prose lives in
brand/register.template.html, evidence lives in records/*.json, and everything
between the BEGIN RECORDS and END RECORDS markers is compiled from the JSON on
every build. If a claim about a subject is not in a record, there is no way to
get it onto the page.

Withdrawn records are compiled too, from records/withdrawn/*.json, and they are
published rather than deleted. A register that quietly removes its mistakes is
asking to be trusted on precisely the point where it was just wrong.

The same reasoning applies to what the page is allowed to say yet. The README
promises that no FAIL_UNSAFE is published until the subject's maintainer has
had the run artifact and seven days to answer, and that promise was being kept
by remembering it. So records now carry a publication block, a held record is
skipped by the public build, and the page reports how many are held and why
without naming them. Withholding the accusation and hiding that anything is
being withheld are different things, and only the first is owed.

Usage:  python3 suite/render_register.py           (writes brand/register.html)
        python3 suite/render_register.py --check   (exit 1 if a page is stale)
        python3 suite/render_register.py --preview (held records visible,
                                                    gitignored, never served)

        Add --publish PATH (repeatable) to write the same gated bytes to
        another location, such as the register page on the live site. Every
        target is written from one build and one pair of guards. Nothing
        downstream re-renders, re-themes, or re-types the page, because a
        second copy maintained beside the first is how this defect has
        arrived every time so far: the hold gets applied to one derived
        artifact and to nothing else that discloses.
"""
import io
import json
import os
import re
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECORDS = os.path.join(ROOT, "records")

# Held records are kept out of version control. They used to sit in records/
# and be committed like everything else, which meant the publication gate held
# the rendered page while the repository carried every withheld finding in
# plain text, verdict field included. What is tracked in their place is
# records/held.manifest.json, which commits to each held file by sha256 and
# discloses nothing about its contents. suite/hold.py maintains and checks it.
# The renderer still reads the records themselves, because the count on the
# public page has to be compiled from evidence rather than typed, or it is one
# more sentence that can drift away from what is true.
HELD_DIR = os.path.join(RECORDS, "held")
MANIFEST_PATH = os.path.join(RECORDS, "held.manifest.json")
MANIFEST_SCHEMA = "nobulex.held.manifest.v0"

# The only publication statuses that permit a record onto the public page.
# Everything else is held, including the absence of a status, because a gate
# whose default is to publish is not a gate. Both spellings are accepted so
# that the vocabulary can be settled without this list being the thing that
# decides it.
CLEARED_FOR_PUBLICATION = frozenset(("CLEARED", "PUBLISHED"))
TEMPLATE = os.path.join(ROOT, "brand", "register.template.html")
OUTPUT = os.path.join(ROOT, "brand", "register.html")

# The public page is the default output, and the one that could end up on a
# domain, so it is the one that is safe. Seeing a held record requires asking
# for it by name, and what comes back is written somewhere that is not served.
#
# That last clause used to be false. The preview was written to brand/, which
# is the directory whose entire purpose is to be published, and it was found
# there being served on every interface by a throwaway `python3 -m http.server`
# left running from an afternoon of previewing the page. Twelve verdict tokens,
# reachable by anyone on the network, while the public page, the repository,
# and the git history had all been fixed. Gitignoring it was never the point;
# the point is that a file which must never be published does not belong in the
# folder that gets published, and a comment asserting a property is not the
# same as a path that has it.
PREVIEW = os.path.join(ROOT, "private", "register.preview.html")

BEGIN = "<!-- BEGIN RECORDS -->"
END = "<!-- END RECORDS -->"

# The verdict colours are the ones already defined in the stylesheet. They are
# named here so a verdict this renderer has never seen cannot silently inherit
# the colour of a verdict it is not.
VERDICT_VAR = {
    "PASS": "--pass",
    "FAIL_SAFE": "--safe",
    "FAIL_UNSAFE": "--unsafe",
    "INDETERMINATE": "--indet",
    "OUT_OF_SCOPE": "--oos",
    "WITHDRAWN": "--unsafe",
    "HELD": "--safe",
}

# Probe outcomes, worst first. This is the order the page asserts in prose
# under every probe tally, and card() now checks the record against it instead
# of asserting it. It is stated here rather than imported from harness.py
# because the renderer reads records and does not run subjects, and a renderer
# that imports the harness inherits everything the harness imports. The
# duplication is the risk that creates, so selftest.py asserts this list is
# identical to harness._ORDER: a second copy is allowed to exist only while
# something fails when the two disagree.
OUTCOME_ORDER = ["FAIL_UNSAFE", "FAIL_SAFE", "INDETERMINATE", "PASS",
                 "OUT_OF_SCOPE"]

# The characters that count as part of a name when matching one inside a
# larger string. `-` is included: a package called mcp does not appear in
# yahoo-finance-mcp, it is part of it. Used by the upstream pin matcher below
# and mirrored by _names().
_WORDISH = r"[0-9A-Za-z_-]"


def _dict(v):
    """A record field that has to be an object, or an empty one.

    `rec.get("subject", {})` returns the null, not the default, when the key
    is present and explicitly set to null, which is a shape run.py can write
    and a shape a hand-edited record can carry. tuple_rows() and card() then
    called .get on None and the whole build died with an AttributeError
    naming a line number. Fail closed and render nothing about a subject
    rather than take the page down: a malformed record must not be able to
    stop the held count and the embargo notice from being published.
    """
    return v if isinstance(v, dict) else {}


def esc(v):
    """HTML-escape. Record text is data and is never trusted as markup."""
    if v is None:
        return ""
    return (str(v).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def day(ts):
    """An ISO timestamp rendered in UTC, or the input unchanged.

    This used to format the datetime as parsed and staple " UTC" onto the end
    of it, which is a claim about the timestamp rather than a rendering of it.
    A record observed at 2026-08-03T13:04:00+02:00 published as
    "2026-08-03 13:04 UTC" when the instant is 11:04 UTC, a two hour error in
    the Observed and Valid until lines, which are the only two the whole record
    is anchored to and the two a reader uses to decide whether a validity
    window has closed. Today's records are all written with a +00:00 offset so
    the printed strings did not move, which is exactly why this survived: the
    defect is invisible until the day a run happens on a machine that is not
    on UTC, and on that day the page is wrong and looks fine.

    A timestamp with no offset at all got the suffix too. That one cannot be
    converted, because nothing in the record says what zone it was written in,
    so it is not converted and it is not labelled UTC either. Printing the
    digits and naming the thing that is missing is the only honest option; the
    alternative is to guess a zone and assert it, which is the failure this
    registry publishes verdicts about.
    """
    if not ts:
        return ""
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return str(ts)
    if dt.tzinfo is None:
        return dt.strftime("%Y-%m-%d %H:%M") + " (no time zone stated)"
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def load(dirpath):
    """Every .json directly inside dirpath, ordered by record_id."""
    if not os.path.isdir(dirpath):
        return []
    out = []
    for name in sorted(os.listdir(dirpath)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(dirpath, name)
        if not os.path.isfile(path):
            continue
        with io.open(path, encoding="utf-8") as fh:
            out.append((name, json.load(fh)))
    return sorted(out, key=lambda p: p[1].get("record_id", p[0]))


def is_withdrawn(rec):
    """A record the registry retracted. Retracted is not the same as held."""
    return (rec.get("status") or "").upper() == "WITHDRAWN"


def load_all():
    """Every record this registry has issued, published or not.

    Two directories rather than one, because held records are not in version
    control and published records are. Which directory a record sits in is a
    fact about where it is stored. Whether it may be published is a fact about
    its publication block. Those are read separately and deliberately, so that
    moving a file by hand into the wrong folder cannot make it publishable.
    """
    out = [(n, r) for n, r in load(RECORDS) + load(HELD_DIR)
           if r.get("schema") != MANIFEST_SCHEMA]
    return sorted(out, key=lambda p: p[1].get("record_id", p[0]))


def manifest_record_ids():
    """The held record ids the tracked manifest commits to.

    Entries with no record_id are the reply documents held alongside the
    records. They are committed to as files and are not records, so they are
    not counted here. Returns None when there is no readable manifest, which
    is a different fact from an empty one and is left to the caller.
    """
    try:
        with io.open(MANIFEST_PATH, encoding="utf-8") as fh:
            m = json.load(fh)
    except (IOError, OSError, ValueError):
        return None
    if not isinstance(m, dict) or m.get("schema") != MANIFEST_SCHEMA:
        return None
    entries = m.get("held")
    if not isinstance(entries, list):
        return None
    return set(e["record_id"] for e in entries
               if isinstance(e, dict) and e.get("record_id"))


def missing_held(committed, present):
    """Held records the manifest commits to that this checkout cannot read.

    Held records are deliberately absent from version control, so a clone of
    this repository carries the manifest and none of the files it commits to.
    The held count on the public page is compiled from the records the
    renderer can see, which means running it in such a clone rewrites the page
    to say nothing is held while the tracked manifest commits to three. That
    is a claim about this registry's own conduct compiled from an absence, and
    it is the same defect this suite keeps finding in other people's code: a
    skipped input counted as agreement.

    It is not hypothetical. It was done in a partial checkout during an audit,
    and the page was rewritten to '0 issued and held' before anything noticed.
    What noticed was hold.py --verify-export, which reads the written file --
    one guard, one step too late. Both sets are ids, and this is pure so the
    selftest can drive it.
    """
    if committed is None:
        return set()
    return set(committed) - set(present)


def subject_strings(rec):
    """The strings in a record that tell a reader who it is about.

    Package, origin and commit identify. The rest of the tuple, the
    environment and the suite and the pinned configuration, describes how the
    run was done and identifies nobody, so it is not collected here.

    Two things were being dropped on the way out, and both dropped names rather
    than noise. A length floor of seven characters meant this returned nothing
    at all for ccxt, openbb, tiingo or mcp, so identifies() could not see the
    name it was guarding and the page was free to print it beside the embargo
    notice. And `subject or subject_as_claimed` read whichever came first, so a
    record carrying both disclosed the claimed name unguarded, which is exactly
    the shape of this registry's own withdrawn record: it exists because a
    claimed subject named a version that resolved to nothing.

    Every identifying string is collected now, at any length, from both
    subjects. Short names are handled where the matching happens rather than by
    refusing to look at them, because a guard that cannot see a name cannot
    refuse to publish it.
    """
    out = set()
    for subj in (rec.get("subject"), rec.get("subject_as_claimed")):
        if not isinstance(subj, dict):
            continue
        for key in ("package", "origin", "repository", "commit"):
            val = subj.get(key)
            if isinstance(val, str) and val.strip():
                out.add(val.strip())
                if key == "commit" and len(val) >= 10:
                    out.add(val[:10])
    return out


def short_path(p):
    """A local path with the machine's identity taken off the front.

    The record stores the absolute interpreter path because reproduction needs
    it. The public page needs the part that distinguishes one environment from
    another, which is the venv and nothing above it.
    """
    if not p:
        return ""
    for anchor in ("/subjects/", "/nobulex-registry/"):
        if anchor in p:
            return p.split(anchor, 1)[1]
    return os.path.basename(p)


def row(field, value, pending=False):
    cls = " pending" if pending else ""
    return ('        <div class="row"><div class="f">%s</div>'
            '<div class="val%s">%s</div></div>\n' % (esc(field), cls, value))


def chip(verdict):
    var = VERDICT_VAR.get(verdict, "--indet")
    return ('<div class="verdict" style="color:var(%s);border-color:var(%s)">'
            '%s</div>' % (var, var, esc(verdict)))


ATTEST_GLOSS = {
    "TOOL": "direct calls, no model in the loop",
    "COMPATIBILITY": "does the declared install produce a running server",
    "WORKFLOW": "the tool as reached through an agent",
}


def dist_name(pin):
    """The distribution name at the front of a resolved pin, lower-cased.

    A resolved pin is not always name==version. pip emits PEP 508 direct
    references (`yahoo-finance-mcp @ file:///tmp/x/subj`), extras
    (`pkg[all]==1.0`), and other comparison operators, and one of those is in
    the records right now. Splitting on "==" alone returns a whole file URL for
    the first of those and half a name for the third, and a string that is not
    a name cannot be matched against an upstream as though it were one.
    """
    return re.split(r"[\s\[=<>!~;@]", str(pin), maxsplit=1)[0].strip().lower()


def names_upstream(name, upstream):
    """Does `upstream` name the distribution `name`, on a name boundary?

    The test used to be `name in upstream`, unanchored containment against a
    free-text upstream string, and it published the wrong dependency on a real
    record whose upstream is a git URL ending in -mcp.git: the token mcp
    occurs inside that URL, and the page rendered `mcp==2.2.0` beside a
    sentence
    calling it the dependency the verdict rides on. mcp is the MCP protocol
    library. It is not the subject's upstream, it is not what the probes
    measured, and a reader checking the finding against that pin is checking
    the wrong project's version.

    So the name has to sit on a boundary, with `-` counted as part of a name,
    which is what makes mcp not a match inside yahoo-finance-mcp while
    yahoo-finance-mcp still is, and yfinance still matches the prose upstream
    "Yahoo Finance, via the yfinance package". Missing a pin costs the page one
    row of detail. Naming the wrong one puts a number on the page that the
    record does not support, and this file exists because that happened once.
    """
    if not name or not upstream:
        return False
    return re.search(r"(?<!%s)%s(?!%s)"
                     % (_WORDISH, re.escape(name), _WORDISH),
                     upstream.lower()) is not None


def tuple_rows(rec):
    """The subject tuple, exactly as the record states it."""
    s = _dict(rec.get("subject"))
    cfg = s.get("configuration", {}) or {}
    env = s.get("execution_environment", {}) or {}
    out = ['      <div class="tuple">\n']

    at = rec.get("attestation_type", "")
    gloss = ATTEST_GLOSS.get(at)
    out.append(row("Attestation type",
                   esc(at) + (" (%s)" % esc(gloss) if gloss else "")))
    out.append(row("Package", esc(s.get("package"))))

    commit = s.get("commit") or ""
    tree = s.get("working_tree_clean")
    note = "" if tree is None else (
        " · working tree clean" if tree else " · WORKING TREE DIRTY")
    out.append(row("Commit", esc(commit) + esc(note),
                   pending=(tree is False)))
    if s.get("origin"):
        out.append(row("Origin", esc(s["origin"])))

    bits = [b for b in (cfg.get("transport"),
                        cfg.get("protocol_version"),
                        cfg.get("install_path")) if b]
    if bits:
        out.append(row("Configuration", esc(" · ".join(bits))))

    locks = cfg.get("lockfiles_present") or {}
    for name in sorted(locks):
        out.append(row("Lockfile", "%s sha256:%s"
                       % (esc(name), esc(str(locks[name])[:16]))))

    si = cfg.get("server_info") or {}
    if si:
        # Labelled self-reported on purpose. This is what the server calls
        # itself over MCP. It is not the version of the package it wraps, and
        # the two can differ by a whole major version, because a server is free
        # to answer here with the version of its MCP library rather than the
        # version of the data package its lockfile actually pins. Both are
        # rendered, separately, and neither is presented as the other.
        out.append(row("serverInfo (self-reported)",
                       "%s/%s" % (esc(si.get("name")), esc(si.get("version")))))

    if s.get("upstream"):
        out.append(row("Upstream source", esc(s["upstream"])))

    envbits = [b for b in (env.get("platform"),
                           short_path(env.get("subject_interpreter")),
                           "harness CPython %s" % env["harness_python"]
                           if env.get("harness_python") else None) if b]
    out.append(row("Execution environment", esc(" · ".join(envbits))
                   if envbits else "not pinned", pending=not envbits))

    res = env.get("resolved_dependencies") or []
    dec = env.get("declared_dependencies") or []
    if res or dec:
        # Surface the pin of whatever the record names as its upstream, since
        # that is the dependency the verdict actually rides on.
        up = s.get("upstream") or ""
        keyed = [p for p in res if names_upstream(dist_name(p), up)]
        # An empty declared list means the harness did not capture one, not
        # that the project declares nothing. Reporting it as zero would be the
        # same mistake this registry publishes verdicts about.
        line = "%d resolved pins" % len(res)
        if dec:
            line += ", %d declared ranges" % len(dec)
        if keyed:
            line += " · " + " · ".join(keyed)
        out.append(row("Dependency set", esc(line)))

    for key in sorted(rec.get("authorities", {})):
        a = rec["authorities"][key]
        indep = a.get("independent_of_subject_upstream")
        tag = ("independent of the subject's upstream"
               if indep else "SAME upstream the subject wraps")
        reach = a.get("reachable")
        if reach is False:
            tag += " · unreachable at run time"
        # Not esc(key). row() escapes the field itself, and escaping here as
        # well ran the key through twice, so an authority keyed A&B published
        # as "Authority A&amp;amp;B". Every other call site passes a literal,
        # which is why the double escape only ever showed on a key with an
        # ampersand in it and never on A1 or A2.
        out.append(row("Authority %s" % key,
                       "%s · %s · %s" % (esc(a.get("id")),
                                         esc(a.get("role")), esc(tag)),
                       pending=(indep is False or reach is False)))

    issuer = rec.get("issuer")
    out.append(row("Issuing key",
                   esc(issuer) if issuer else
                   "not yet established. Records are published from the "
                   "repository, not signed, so the office is not yet "
                   "independently verifiable.",
                   pending=not issuer))

    out.append(row("Suite version", "%s · schema %s"
                   % (esc(s.get("suite")), esc(rec.get("schema")))))
    out.append(row("Observed", esc(day(s.get("observed_at")))))

    val = rec.get("validity") or {}
    out.append(row("Valid until", esc(day(val.get("until")))
                   if val.get("until") else
                   "no window issued", pending=not val.get("until")))

    # Only shown when the record is held, which today means only in the
    # preview, since the public build never receives a held record at all.
    pub = rec.get("publication") or {}
    ror = pub.get("right_of_reply") or {}
    if pub.get("status") == "HELD":
        out.append(row("Publication",
                       "HELD &nbsp;·&nbsp; gate: %s" % esc(pub.get("held_by")),
                       pending=True))
        out.append(row("Right of reply",
                       "artifact not yet delivered, window not started"
                       if not ror.get("artifact_delivered_at") else
                       "delivered %s, closes %s"
                       % (esc(day(ror.get("artifact_delivered_at"))),
                          esc(day(ror.get("window_closes_at")))),
                       pending=not ror.get("reply_received_at")))
    out.append("      </div>\n")
    return "".join(out)


def probe_table(rec):
    """Every probe that ran, including the ones that passed.

    A register that lists only the probes that found something is publishing a
    highlight reel. The denominator is part of the evidence.
    """
    probes = rec.get("probes") or []
    if not probes:
        return ""
    out = ['      <div class="probes">\n',
           '        <div class="phead"><div>id</div><div>probe and what it '
           'observed</div><div style="text-align:right">outcome</div></div>\n']
    for p in probes:
        var = VERDICT_VAR.get(p.get("outcome"), "--indet")
        cause = p.get("loss_cause")
        out.append('        <div class="pr">'
                   '<div class="pid">%s</div>'
                   '<div class="pdesc">%s<span class="ev">%s</span></div>'
                   '<div class="pout" style="color:var(%s)">%s%s</div>'
                   '</div>\n'
                   % (esc(p.get("probe")), esc(p.get("description")),
                      esc(p.get("detail")), var, esc(p.get("outcome")),
                      "<br>%s" % esc(cause) if cause else ""))
    out.append("      </div>\n")
    return "".join(out)


def tally(rec):
    """Outcome counts, so the verdict can be checked against the probes."""
    counts = {}
    for p in rec.get("probes") or []:
        counts[p.get("outcome")] = counts.get(p.get("outcome"), 0) + 1
    seen = [k for k in OUTCOME_ORDER if k in counts] + \
           [k for k in sorted(counts) if k not in OUTCOME_ORDER]
    return " · ".join("%d %s" % (counts[k], k) for k in seen)


def verdict_disagrees(rec):
    """Why the record's verdict is not the worst outcome its probes recorded.

    Returns a sentence, or "" when the record and its own probes agree.

    The page prints, under every tally, "The verdict is the worst outcome
    observed, in the order FAIL_UNSAFE, FAIL_SAFE, INDETERMINATE, PASS,
    OUT_OF_SCOPE." Nothing computed that. The sentence was rendered from a
    constant beside a table of counts that could say anything, so a record
    carrying verdict PASS and a FAIL_UNSAFE probe published both, with a
    sentence between them asserting the two were the same thing. That is the
    register contradicting itself on the page and calling the contradiction a
    rule, which is worse than either half alone: a reader who trusts the
    sentence reads the wrong verdict and a reader who reads the table cannot
    tell which of the two the registry means.

    An outcome this file cannot rank is a disagreement too, not a pass. It
    cannot be shown to be the worst and the page would be asserting that it is.
    """
    probes = rec.get("probes") or []
    if not probes:
        return ""
    outcomes = [p.get("outcome") for p in probes]
    unknown = sorted({str(o) for o in outcomes if o not in OUTCOME_ORDER})
    if unknown:
        return ("probe outcome %s cannot be ranked, so the record cannot be "
                "shown to carry the worst one" % ", ".join(unknown))
    worst = next(o for o in OUTCOME_ORDER if o in outcomes)
    verdict = rec.get("verdict")
    if verdict != worst:
        return ("verdict is %s and the worst outcome its probes recorded is %s"
                % (verdict, worst))
    return ""


def card(rec):
    # Refuse before a single byte of the card is built, for the same reason
    # build() refuses on an embargo notice that names a verdict: a page that
    # contradicts itself should not exist on disk, not even briefly, and the
    # fix belongs in the record rather than in the renderer that printed it.
    why = verdict_disagrees(rec)
    if why:
        raise SystemExit(
            "record %s does not carry the verdict its own probes support: %s.\n"
            "  Nothing was written. The page states under every tally that the\n"
            "  verdict is the worst outcome observed, so publishing this one\n"
            "  publishes the sentence and the counterexample together. Re-run\n"
            "  the subject under newly pinned conditions, or correct the\n"
            "  record. Do not edit the sentence."
            % (rec.get("record_id", "(no record_id)"), why))

    rid = rec.get("record_id", "")
    number = rid.split("-")[-1] if "-" in rid else rid
    s = _dict(rec.get("subject"))
    commit = (s.get("commit") or "")[:7]
    verdict = rec.get("verdict", "INDETERMINATE")
    var = VERDICT_VAR.get(verdict, "--indet")

    out = ['    <div class="rec">\n',
           '      <div class="rechead">\n        <div>\n',
           '          <div class="recno">Record No. %s &nbsp;·&nbsp; %s</div>\n'
           % (esc(number), esc(rid)),
           '          <div class="recsub">%s @ %s</div>\n'
           % (esc(s.get("package")), esc(commit)),
           '        </div>\n        %s\n      </div>\n' % chip(verdict)]

    causes = rec.get("loss_causes") or []
    if causes:
        out.append('      <div class="causes">%s</div>\n'
                   % "".join('<span class="cause">%s</span>' % esc(c)
                             for c in causes))

    out.append(tuple_rows(rec))

    summary = rec.get("summary")
    if summary:
        out.append('      <div class="why" style="border-left-color:var(%s)">'
                   '<b>Why this verdict.</b> %s</div>\n' % (var, esc(summary)))

    t = tally(rec)
    if t:
        # The order is written out of OUTCOME_ORDER rather than typed, because
        # it is the same list verdict_disagrees() checked the record against a
        # few lines above. Typed, it is a sentence that can drift away from the
        # rule it describes while both keep rendering.
        out.append('      <div class="why" style="border-left-color:var(--rule)">'
                   '<b>Probe tally.</b> %s. The verdict is the worst outcome '
                   'observed, in the order %s. It is never an average '
                   'and never a score.</div>\n'
                   % (esc(t), esc(", ".join(OUTCOME_ORDER))))

    out.append(probe_table(rec))
    out.append('    </div>\n')
    return "".join(out)


def withdrawal_card(w, held_ids=()):
    """A withdrawn record, published with the reason attached.

    held_ids are records that exist but may not be published yet. A withdrawal
    naming one of them as a successor would put the held record's identity on
    the public page next to a named subject, and a reader who sees an id with
    no verdict attached will supply one. So held successors are counted, not
    named.
    """
    rid = w.get("record_id", "")
    number = rid.split("-")[-1] if "-" in rid else rid
    s = w.get("subject_as_claimed", {}) or {}
    out = ['    <div class="rec wd">\n',
           '      <div class="rechead">\n        <div>\n',
           '          <div class="recno">Record No. %s &nbsp;·&nbsp; %s</div>\n'
           % (esc(number), esc(rid)),
           '          <div class="recsub">%s @ %s</div>\n'
           % (esc(s.get("package")), esc(s.get("commit"))),
           '        </div>\n        %s\n      </div>\n'
           % chip("WITHDRAWN"),
           '      <div class="tuple">\n']

    out.append(row("Subject as claimed",
                   "%s @ %s" % (esc(s.get("package")), esc(s.get("commit"))),
                   pending=True))
    ev = w.get("evidence") or {}
    if ev.get("check"):
        out.append(row("Resolution check", "%s &rarr; %s"
                       % (esc(ev["check"]), esc(ev.get("result")))))
    if ev.get("commits_reachable_from_all_refs") is not None:
        out.append(row("Repository searched",
                       "%s commits reachable from all refs, %s with that prefix"
                       % (esc(ev["commits_reachable_from_all_refs"]),
                          esc(ev.get("commits_with_that_prefix", 0)))))

    for h in w.get("verdict_history") or []:
        out.append(row("Verdict, withdrawn",
                       "%s &nbsp;·&nbsp; %s" % (esc(h.get("verdict")),
                                          esc(h.get("reason"))),
                       pending=True))
    sup = w.get("superseded_by") or []
    if sup:
        named = [x for x in sup if x not in held_ids]
        hidden = len(sup) - len(named)
        txt = ", ".join(named)
        if hidden:
            unpub = ("%d not yet published" % hidden if named
                     else "%d record%s, none yet published"
                     % (hidden, "" if hidden == 1 else "s"))
            txt = (txt + ", and " + unpub) if named else unpub
        out.append(row("Superseded by", esc(txt), pending=bool(hidden)))
    out.append(row("Withdrawn", esc(day(w.get("withdrawn_at")))))
    out.append("      </div>\n")

    if w.get("reason"):
        out.append('      <div class="why" style="border-left-color:var(--unsafe)">'
                   '<b>Why it was withdrawn.</b> %s</div>\n' % esc(w["reason"]))
    if w.get("principle"):
        out.append('      <div class="why" style="border-left-color:var(--rule)">'
                   '<b>The rule this establishes.</b> %s</div>\n'
                   % esc(w["principle"]))
    if w.get("superseded_note"):
        out.append('      <div class="why" style="border-left-color:var(--rule)">'
                   '<b>What replaced it.</b> %s</div>\n'
                   % esc(w["superseded_note"]))
    out.append('    </div>\n')
    return "".join(out)


def is_held(rec):
    """A record the registry has issued but is not entitled to publish yet.

    The rule it enforces is the one the README already made: before a
    FAIL_UNSAFE is published, the maintainer of the subject gets the full run
    artifact and seven days to answer. That promise was being kept by memory,
    which is not a mechanism. A record is held until its own publication block
    says the gate cleared, and the public build never sees a held record, so
    forgetting is no longer one of the available outcomes.

    Holding is not softening. The verdict does not change while the window
    runs, the reply cannot change it when it arrives, and the reply publishes
    unedited beside the record. All the window buys the subject is the chance
    to be heard at the same time as everyone else, instead of afterwards.

    This used to read `status == "HELD"`, which made the gate opt in. Every
    other value published, including no publication block at all, including the
    same word in lower case while the sibling is_withdrawn() upper-cased before
    comparing. run.py writes no publication block, so a record straight out of
    the harness satisfied none of the conditions for being held and all of the
    conditions for being rendered. load_all() says in its own docstring that
    moving a file by hand into the wrong folder cannot make it publishable,
    which was true, while forgetting to hand-add a field to it could.

    So the default is now what the paragraph above always claimed: held. A
    record publishes when its publication block says the gate cleared, and in
    no other circumstance, including every circumstance nobody thought of.
    """
    status = (rec.get("publication") or {}).get("status")
    if not isinstance(status, str):
        return True
    return status.strip().upper() not in CLEARED_FOR_PUBLICATION


def embargo_block(held):
    """Say that something is being withheld, without saying what it found.

    The thing being protected is the verdict, not the fact of a test. An earlier
    version of this block named FAIL_UNSAFE while describing the gate, and the
    rules say the gate applies before publication, so a reader could resolve
    "one record held under right of reply" into "there is an unpublished
    FAIL_UNSAFE" and then, from the withdrawal card, into which subject it was
    about. That is worse than publishing the record. The published record is
    checkable and answerable; a verdict inferred from an embargo notice is
    neither, and the maintainer cannot reply to evidence nobody has shown.

    So this block states the mechanism and the count and no verdict at all, and
    build() refuses to compile a version of it that names one.
    """
    if not held:
        return ""
    gates = sorted({(r.get("publication") or {}).get("held_by") or "unstated"
                    for _, r in held})
    out = [
        '    <div class="embargo">\n'
        '      <div class="ehead">Held, not published</div>\n'
        '      <b>%d record%s issued and withheld.</b>\n'
        '      <p>Gate: %s. A record whose finding is adverse to a named '
        'maintainer is not published on the day it is issued. That maintainer '
        'first receives the full run artifact and has seven days to answer, '
        'and the answer publishes beside the record, unedited. The verdict is '
        'fixed before the window opens and the window cannot change it; only a '
        'new run under newly pinned conditions can.</p>\n'
        % (len(held), "" if len(held) == 1 else "s",
           esc(", ".join(gates).replace("_", " ")))]

    # "One of these" was typed, behind an any() that only asked whether there
    # was at least one. With two withheld withdrawals the header said 4 and the
    # body said One, so the page carried two different counts of the same set
    # and neither was compiled from the records. It is the drift this whole
    # generator exists to make impossible, arrived at through prose instead of
    # through a number, and prose is where the count is least likely to be
    # checked. The rest of the paragraph is written to hold for any count, so
    # there is one version of it rather than a singular and a plural that can
    # be edited apart.
    n_wd = sum(1 for _, r in held if is_withdrawn(r))
    if n_wd:
        out.append(
            '      <p>%s of these %s this registry\'s own withdrawn record%s, '
            'adverse to nobody but us. Such a record would have published the '
            'day it was written, except that its subject is the same package '
            'as the records now under reply and is the only subject this page '
            'would name at all. Publishing it says that Nobulex is '
            'withholding adverse findings about one identified project while '
            'showing none of the evidence for them. That is the accusation '
            'the window exists to prevent, minus everything the maintainer '
            'would need to answer it. It publishes when they do. Nothing was '
            'ever served to a reader who would now be owed the correction, so '
            'holding it costs that reader nothing.</p>\n'
            % ("One" if n_wd == 1 else "%d" % n_wd,
               "is" if n_wd == 1 else "are", "" if n_wd == 1 else "s"))

    out.append(
        '      <p>What a held record found is not stated here, not its '
        'verdict and not who it is about, because a finding a reader can '
        'infer but nobody can check is worse than one published in full. The '
        'count is compiled from the records, so a held record can be '
        'forgotten about but cannot be hidden.</p>\n'
        '      <p>Each held record is committed to by sha256 in '
        '<code>records/held.manifest.json</code>, which is in version control '
        'while the records themselves are not. When one publishes, hash it. '
        'Matching the value committed on the day it was issued is what makes '
        '&ldquo;the verdict is fixed before the window opens&rdquo; something '
        'a stranger can check rather than something we assert.</p>\n'
        '    </div>\n')
    return "".join(out)


def leaked(html, held_ids):
    """Held record ids that survived into a page that may not name them.

    A held record can reach the public page without being rendered on it. Its
    id can arrive inside another record's superseded_by list, or inside a
    sentence someone wrote in a summary field months ago. The page then carries
    an identifier with no verdict attached to it, next to an embargo notice
    saying a FAIL_UNSAFE is being withheld, and a reader who can read joins the
    two. That is worse than publishing and worse than withholding, because the
    verdict the reader supplies is one nobody is accountable for.

    So this is checked against the finished html rather than against the
    records, because the leak is a property of the output, not of any one
    input. Every path that produced this string is covered, including the ones
    added after this function was written.
    """
    return sorted(i for i in held_ids if i and i in html)


def _names(html, needle):
    """Does this page name `needle`, as the page actually spells it?

    Two ways this missed. The page is written through esc(), so a subject
    called acme&co-mcp reaches the html as acme&amp;co-mcp while a raw
    substring search looks for acme&co-mcp and finds nothing. And a raw
    substring search is the wrong instrument for short names in the other
    direction too, since a three letter package matches inside unrelated words.

    So the needle is compared in both its raw and its escaped spelling, and it
    must sit on a word boundary. A false positive here refuses a page that was
    clean, which costs a build. A false negative publishes the name of a
    project this registry is withholding a finding about. Those are not
    comparable, and this errs toward the first.
    """
    for form in {needle, esc(needle)}:
        if re.search(r"(?<![0-9A-Za-z_-])%s(?![0-9A-Za-z_-])"
                     % re.escape(form), html):
            return True
    return False


def identifies(html, held):
    """Held subjects the page names anyway, which is the same leak one level up.

    Stripping the record ids was not enough, and the reason it was not enough
    is worth keeping written down. Right of reply now covers every adverse
    verdict, so a record held under that gate is adverse by definition. The
    page states the gate and the count. The withdrawal card named the package.
    Those three facts join into "Nobulex is withholding an adverse finding
    about this named project", which is an accusation with no evidence behind
    it and nothing in it for the maintainer to answer. It is the harm the
    window exists to prevent, arrived at without a single verdict on the page.

    So while a record is held, the page names no held subject at all. That
    looks like a heavy rule and it is the existing rule applied honestly: a
    count and a mechanism may be published, and anything that identifies is
    part of the finding. Today it means the register publishes no subject
    whatsoever, which is the true state of a registry whose every record is
    waiting on someone else.
    """
    out = set()
    for _, rec in held:
        for s in subject_strings(rec):
            if _names(html, s):
                out.add(s)
    return sorted(out)


def build(preview=False):
    """Compile the page. Public by default; preview shows what is held."""
    everything = load_all()

    held = [(p, r) for p, r in everything if is_held(r)]
    held_ids = {r.get("record_id") for _, r in held}
    visible = everything if preview else [(p, r) for p, r in everything
                                          if not is_held(r)]
    shown = [(p, r) for p, r in visible if not is_withdrawn(r)]
    dead = [(p, r) for p, r in visible if is_withdrawn(r)]

    # Held and withdrawn are two different facts and a record can carry both.
    # Held describes what the registry may publish yet; withdrawn describes
    # whether the record still stands. The public note used to add them into
    # one number: a record that was both fell out of `visible`, so it never
    # reached `dead`, and it was counted under "issued and held" beside a
    # sentence reading "A held record is in force: it is issued, its verdict is
    # fixed". That is asserted, on the public page, about a record this
    # registry retracted. It is the register overstating its own live findings,
    # which is precisely the class of claim it publishes verdicts about in
    # other people's software, and it is live in today's records: one of the
    # four withheld records is the withdrawn one.
    #
    # So the two are counted apart and both are printed. A withheld withdrawal
    # is disclosed as its own number rather than folded into either the live
    # holds or the published withdrawals, because collapsing it into one of
    # them is how it went unnoticed.
    held_live = [(p, r) for p, r in held if not is_withdrawn(r)]
    held_dead = [(p, r) for p, r in held if is_withdrawn(r)]

    body = []
    if not preview:
        block = embargo_block(held)
        # The bug this catches is the one that was actually here: prose in the
        # embargo notice that names a verdict class, which combined with a rule
        # saying when that class is gated tells the reader what the held record
        # found. It is checked rather than merely commented because the block is
        # prose, and prose is edited by people who are thinking about a sentence
        # rather than about what the sentence discloses.
        named = [v for v in VERDICT_VAR if v not in ("HELD",) and v in block]
        if named:
            raise SystemExit(
                "the embargo notice names %s. It may state that records are "
                "held and how many, never what they found: a verdict a reader "
                "infers is one the subject cannot answer." % ", ".join(named))
        body.append(block)
    for _, rec in shown:
        body.append(card(rec))
    for _, w in dead:
        body.append(withdrawal_card(w, () if preview else held_ids))

    if preview:
        note = ('    <p class="note">PREVIEW. %d record%s in force, %d of '
                'them held from the public register, and %d withdrawn. This '
                'file is not the published page and is not committed. Build '
                'without --preview to produce what may be served.</p>\n'
                % (len(shown), "" if len(shown) == 1 else "s",
                   len(held), len(dead)))
    else:
        empty = ""
        if not shown and not dead:
            empty = ('Every record this registry has issued is currently '
                     'held, so this page carries its rules and its count and '
                     'no subject at all. That is the accurate state of it, '
                     'not an empty template. ')
        # Each clause below is emitted only when the count it explains is
        # nonzero, so the page cannot assert "a held record is in force" on a
        # build where nothing is held and in force.
        inforce = ""
        if held_live:
            inforce = ('A held record is in force: it is issued, its verdict '
                       'is fixed, and it is waiting on its subject rather '
                       'than on us. ')
        retracted = ""
        if held_dead:
            retracted = ('A record that is withdrawn and held is not in '
                         'force. It was retracted, and it is counted on its '
                         'own line rather than among the records waiting on a '
                         'reply, because a retraction added to the live holds '
                         'is this register overstating what it currently '
                         'finds. ')
        note = ('    <p class="note">%d record%s published, %d issued and '
                'held, %d withdrawn and held, and %d withdrawn and published, '
                'compiled from the records on every build. %s%s%sNothing on '
                'this page is typed by hand, because the one time it was, it '
                'published a subject that could not be resolved.</p>\n'
                % (len(shown), "" if len(shown) == 1 else "s",
                   len(held_live), len(held_dead), len(dead),
                   empty, inforce, retracted))
    body.append(note)

    with io.open(TEMPLATE, encoding="utf-8") as fh:
        tmpl = fh.read()
    i = tmpl.index(BEGIN) + len(BEGIN)
    j = tmpl.index(END)
    html = tmpl[:i] + "\n" + "".join(body) + "    " + tmpl[j:]
    return html, len(shown), len(held), len(dead), held_ids, held


def read_if_present(path):
    if not os.path.exists(path):
        return None
    with io.open(path, encoding="utf-8") as fh:
        return fh.read()


def targets(argv):
    """Every path the gated page is written to.

    There is one build and one pair of guards, and then identical bytes to
    each target. Adding a target does not add a place where the page could
    be different, which is the entire reason this is a list here rather
    than a copy step somewhere downstream. A copy step is a second author,
    and a second author of this page is a second chance to publish a name
    that is under embargo.
    """
    out = [OUTPUT]
    i = 0
    while i < len(argv):
        if argv[i] == "--publish" and i + 1 < len(argv):
            p = os.path.abspath(os.path.expanduser(argv[i + 1]))
            if p not in out:
                out.append(p)
            i += 2
            continue
        i += 1
    return out


def main(argv):
    # Before anything is read for rendering, and before --check compares the
    # published copies against a build, confirm this checkout can actually see
    # the records it is about to compile a count from. Rendering from a
    # partial clone does not fail: it succeeds and publishes a smaller number.
    committed = manifest_record_ids()
    if committed is None and os.path.exists(MANIFEST_PATH):
        sys.stderr.write(
            "REFUSED: %s is present but could not be read as a manifest.\n"
            "  Nothing was written. An unreadable manifest is not an empty\n"
            "  one, and the check that this checkout holds every record it\n"
            "  commits to cannot run without it. Repair it, or run\n"
            "  suite/hold.py --commit where the records live to rewrite it.\n"
            % os.path.relpath(MANIFEST_PATH, ROOT))
        return 2
    absent = missing_held(committed, set(
        r.get("record_id") for _, r in load(HELD_DIR)))
    if absent:
        sys.stderr.write(
            "REFUSED: the manifest commits to %d held record%s and %d of them\n"
            "  cannot be read here.\n"
            "  %s\n"
            "  Nothing was written. Held records are not in version control,\n"
            "  so this is the expected state of a fresh or partial clone, and\n"
            "  the renderer compiles the held count from the records it can\n"
            "  see. Building here would publish '0 issued and held' over a\n"
            "  manifest that commits to more, which reads as this registry\n"
            "  having quietly dropped findings it is holding. Build where the\n"
            "  records live.\n"
            % (len(committed), "" if len(committed) == 1 else "s",
               len(absent), ", ".join(sorted(absent))))
        return 2

    if "--preview" in argv:
        html, n_shown, n_held, n_dead, _, _ = build(preview=True)
        d = os.path.dirname(PREVIEW)
        if not os.path.isdir(d):
            os.makedirs(d)
        with io.open(PREVIEW, "w", encoding="utf-8") as fh:
            fh.write(html)
        print("wrote %s" % os.path.relpath(PREVIEW, ROOT))
        print("  %d shown (%d of them HELD), %d withdrawn"
              % (n_shown, n_held, n_dead))
        print("  private/ is not tracked and is not a publish root. Do not")
        print("  point a server at it and do not copy this file into brand/.")
        return 0

    html, n_pub, n_held, n_dead, held_ids, held = build()

    # Both checks run before anything is written, because a page that names
    # what it is withholding should not exist on disk at all, not even
    # briefly. Each says what it found and leaves locating the source to a
    # grep, since the source is nearly always prose, and prose is where the
    # fix has to be made anyway.
    escaped = leaked(html, held_ids)
    if escaped:
        sys.stderr.write(
            "REFUSED: the public page names %d record%s it is withholding.\n"
            "  %s\n"
            "  Nothing was written. A held id on the page has no verdict\n"
            "  attached to it, so the reader supplies one. Find the source\n"
            "  (usually a summary field or a superseded_by list) and remove\n"
            "  the reference, then build again.\n"
            % (len(escaped), "" if len(escaped) == 1 else "s",
               ", ".join(escaped)))
        return 2

    named = identifies(html, held)
    if named:
        sys.stderr.write(
            "REFUSED: the public page identifies the subject of a record it\n"
            "  is withholding.\n"
            "  %s\n"
            "  Nothing was written. Right of reply covers every adverse\n"
            "  verdict, so a held record is adverse by definition, and a page\n"
            "  that says it is holding records and names who they are about\n"
            "  has published the accusation and withheld the evidence for it.\n"
            "  That is the harm the window exists to prevent, and it does not\n"
            "  require a verdict to appear anywhere on the page.\n"
            % "\n  ".join(named))
        return 2

    paths = targets(argv)

    if "--check" in argv:
        stale = [p for p in paths if read_if_present(p) != html]
        if not stale:
            print("register is current in %d place%s (%d published, %d held, "
                  "%d withdrawn)"
                  % (len(paths), "" if len(paths) == 1 else "s",
                     n_pub, n_held, n_dead))
            return 0
        sys.stderr.write(
            "STALE: %d published cop%s of the register does not match "
            "records/.\n" % (len(stale), "y" if len(stale) == 1 else "ies"))
        for p in stale:
            sys.stderr.write("  %s\n" % p)
        sys.stderr.write(
            "  Re-run the renderer with the same --publish targets. Do not\n"
            "  edit a published copy to match; the copy is output, and the\n"
            "  records are the source.\n")
        return 1

    for p in paths:
        d = os.path.dirname(p)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        with io.open(p, "w", encoding="utf-8") as fh:
            fh.write(html)
        print("wrote %s" % p)
    print("  %d record%s published, %d held, %d withdrawn"
          % (n_pub, "" if n_pub == 1 else "s", n_held, n_dead))
    if n_held:
        print("  held records are absent from this file by construction, "
              "not by choice at build time")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
