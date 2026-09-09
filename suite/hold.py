#!/usr/bin/env python3
"""Commit to a withheld record without disclosing what it says.

A record under right of reply cannot be published, and it also cannot simply
be trusted. The rule says the verdict is fixed before the window opens and
that the window cannot change it, and until now that rule was kept by
intending to keep it. Nothing stopped a held record from being quietly edited
after its subject had seen it, and nothing would have shown it afterwards.

Keeping the held records in git looked like it answered that, and it did
answer it, by publishing the finding to anyone who cloned the repository. The
publication gate held the rendered page and left the evidence in the open, so
the first push would have disclosed every verdict the hold exists to withhold.
Two properties are wanted at once: a held record must be unalterable, and it
must be unreadable until its subject has answered.

A hash commitment gives both. The held records live outside version control.
What is committed is this manifest: for each held file, its identifier, the
gate holding it, and its sha256. None of that says what the record found. When
the record publishes, anyone can hash the published file and compare it to the
value committed on the day it was issued. Matching means the verdict was not
touched while the window was open. Not matching means the registry is caught
by its own repository history, which is the point.

Two things this is not. It is not a formal commitment scheme: there is no
nonce, and it relies on the record carrying enough entropy of its own (run
timestamps, probe output, a hashed lockfile, an environment fingerprint) that
the content cannot be recovered by guessing candidate documents and hashing
them. That holds for these records and would not hold for a one-line one. And
it is not a timestamp: it proves the content is unchanged since the commit
that carried the manifest, and the commit date is only as trustworthy as the
person who set it. An external anchor is one of the project's stated gaps.

The manifest omits the subject on purpose. A record held under right of reply
is by definition adverse, so naming its subject would publish the accusation
while withholding the evidence for it, which is the harm the window exists to
prevent. The commitment is to the content, never to who it is about.

These three commands run where the held records live. The public export is a
different repository with a different job: it carries the manifest and must
never carry the records, so every check above inverts there, and running the
wrong one is loud in both directions. See --verify-export.

Usage:  python3 suite/hold.py --commit   (write the manifest from the records)
        python3 suite/hold.py --commit --amend
                                         (also rewrite a commitment HEAD
                                          already carries, which --commit
                                          refuses to do quietly)
        python3 suite/hold.py --verify   (fail if a held record was altered,
                                          or if the manifest committing to it
                                          was itself rewritten)
        python3 suite/hold.py --audit    (also search git for leaked content)
        python3 suite/hold.py --verify-export
                                         (for the public repo, where the
                                          records must be absent, not intact)
"""
import hashlib
import io
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECORDS = os.path.join(ROOT, "records")
HELD = os.path.join(ROOT, "records", "held")
MANIFEST = os.path.join(ROOT, "records", "held.manifest.json")
REGISTER = os.path.join(ROOT, "brand", "register.html")


def sha256(path):
    h = hashlib.sha256()
    with io.open(path, "rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def held_names():
    """Every file in the held directory, in a stable order."""
    if not os.path.isdir(HELD):
        return []
    return sorted(n for n in os.listdir(HELD)
                  if os.path.isfile(os.path.join(HELD, n))
                  and not n.startswith("."))


def entry(name):
    """The publishable facts about one held file, and nothing beyond them.

    A .json here is a record and can state its own id and gate without saying
    anything about its finding. A .md here is the notice that will be sent to
    the subject, so it is listed by filename and hashed and never read into
    anything that gets written down: its prose is the finding in full.
    """
    path = os.path.join(HELD, name)
    row = {"file": name, "bytes": os.path.getsize(path),
           "sha256": sha256(path)}
    if name.endswith(".json"):
        with io.open(path, encoding="utf-8") as fh:
            rec = json.load(fh)
        pub = rec.get("publication") or {}
        row["record_id"] = rec.get("record_id")
        row["held_by"] = pub.get("held_by") or "unstated"
        row["publication_status"] = pub.get("status") or "unstated"
    return row


def git(args):
    """git, or None if it is not there and not usable."""
    try:
        return subprocess.check_output(["git"] + args, cwd=ROOT,
                                       stderr=subprocess.DEVNULL
                                       ).decode("utf-8", "replace")
    except Exception:
        return None


def history_leaks(ids):
    """Held records whose content is reachable from a commit in this repo.

    Moving the records out of git protects the next push and does nothing at
    all about the commits that already carry them, and those commits are
    exactly what a clone hands over. So history is read rather than assumed
    clean. This parses candidate blobs and matches on record id; it never
    prints, returns, or stores anything it found inside one.
    """
    revs = git(["rev-list", "--all"])
    if revs is None:
        return None
    manifest_name = os.path.basename(MANIFEST)
    hits = {}
    for rev in revs.split():
        listing = git(["ls-tree", "-r", "--name-only", rev]) or ""
        for path in listing.splitlines():
            if not path.startswith("records/") or not path.endswith(".json"):
                continue
            if os.path.basename(path) == manifest_name:
                continue
            blob = git(["cat-file", "-p", "%s:%s" % (rev, path)])
            if not blob:
                continue
            try:
                rec = json.loads(blob)
            except ValueError:
                continue
            if rec.get("record_id") in ids:
                hits.setdefault(rec["record_id"], set()).add(path)
    return hits


MANIFEST_PURPOSE = (
    "Each entry commits to one held file by sha256 without disclosing what it "
    "says. When the file publishes, hash it and compare: equal means the "
    "record was not altered while its subject held the right to answer it. "
    "The subject is deliberately absent, because a record held under right of "
    "reply is adverse by definition, and naming who it is about would publish "
    "the accusation while withholding the evidence for it.")


def manifest_at_head():
    """The manifest as the last commit has it, keyed by file name.

    Returns None when git cannot answer, which is a different fact from an
    empty manifest and is left to the caller to say out loud.
    """
    rel = os.path.relpath(MANIFEST, ROOT).replace(os.sep, "/")
    blob = git(["show", "HEAD:%s" % rel])
    if blob is None:
        return None
    try:
        m = json.loads(blob)
    except ValueError:
        return None
    if not isinstance(m, dict):
        return None
    return {r["file"]: r for r in m.get("held", [])
            if isinstance(r, dict) and r.get("file")}


def rewritten_commitments(head, disk):
    """Entries whose sha256 differs between the manifest in HEAD and the one
    on disk. Returns [(file, was_sha, now_sha, was_bytes, now_bytes)].

    This is the hole --verify had. It compared the held records against the
    manifest sitting next to them, so altering a record and re-running
    --commit produced two files that agree with each other and a green check
    that said "all matching the committed hashes". Nothing was committed. The
    commitment is only worth something while it is compared against a version
    of the manifest that is in history and cannot be rewritten by the same
    hand that rewrote the record.

    It was not hypothetical when this was written: a held record under an open
    reply window was 1009 bytes larger than the manifest committed to five
    hours earlier, the manifest on disk had been regenerated to match, and
    --verify reported seven files clean. git status was the only thing that
    knew.

    Pure, and takes both sides as arguments, so the selftest can drive it
    without a repository.
    """
    out = []
    for name, was in sorted((head or {}).items()):
        now = (disk or {}).get(name)
        if now is None:
            continue
        if was.get("sha256") != now.get("sha256"):
            out.append((name, was.get("sha256"), now.get("sha256"),
                        was.get("bytes"), now.get("bytes")))
    return out


def dropped_commitments(head, disk):
    """Files HEAD commits to that the manifest on disk no longer lists.

    Deleting the entry is the other way to make an altered record verify
    clean, and it leaves less of a trace than changing the hash.
    """
    return sorted(set(head or {}) - set(disk or {}))


def cmd_commit(amend=False):
    names = held_names()
    manifest = {
        "schema": "nobulex.held.manifest.v0",
        "purpose": MANIFEST_PURPOSE,
        "held_count": len(names),
        "held": [entry(n) for n in names],
    }

    # Rewriting an entry that HEAD already commits to is how a commitment
    # stops being one: the record is edited, this command is re-run, and every
    # check downstream compares two files that were changed together. Adding a
    # new record is the ordinary case and is not this. Amending an existing
    # one has to be asked for by name, so that it appears in the shell history
    # and in whatever the person writes in the commit message afterwards.
    head = manifest_at_head()
    fresh = {r["file"]: r for r in manifest["held"]}
    would_rewrite = rewritten_commitments(head, fresh)
    if would_rewrite and not amend:
        sys.stderr.write("REFUSED: this would rewrite a commitment already "
                         "in HEAD.\n")
        for name, was, now, wb, nb in would_rewrite:
            sys.stderr.write(
                "  %s\n    HEAD: %s bytes  %s\n    disk: %s bytes  %s\n"
                % (name, wb, (was or "")[:16], nb, (now or "")[:16]))
        sys.stderr.write(
            "  Nothing was written. The manifest is what fixes a held\n"
            "  record's contents while its subject has the right to answer\n"
            "  it, so replacing the hash of a record that is already\n"
            "  committed to is the one edit this file exists to make\n"
            "  difficult. If the record legitimately changed, re-run with\n"
            "  --amend and say in the commit message what changed and why.\n")
        return 2
    # No generation timestamp anywhere in here. A timestamp would change the
    # file on every run, which makes the diff meaningless, and a manifest
    # whose diff is meaningless cannot be used to show that nothing changed.
    text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    with io.open(MANIFEST, "w", encoding="utf-8") as fh:
        fh.write(text)
    print("wrote %s" % os.path.relpath(MANIFEST, ROOT))
    for row in manifest["held"]:
        print("  %s  %s" % (row["sha256"][:16], row["file"]))
    print("  %d held file%s committed by hash, contents not committed"
          % (len(names), "" if len(names) == 1 else "s"))
    return 0


def cmd_verify(quiet=False):
    """Fail if a held record is not byte for byte what was committed to."""
    if not os.path.exists(MANIFEST):
        sys.stderr.write(
            "no %s. Run: python3 suite/hold.py --commit\n"
            % os.path.relpath(MANIFEST, ROOT))
        return 2
    with io.open(MANIFEST, encoding="utf-8") as fh:
        manifest = json.load(fh)
    want = {r["file"]: r for r in manifest.get("held", [])}
    have = set(held_names())

    altered = sorted(n for n in (have & set(want))
                     if sha256(os.path.join(HELD, n)) != want[n]["sha256"])
    missing = sorted(set(want) - have)
    uncommitted = sorted(have - set(want))

    if altered:
        sys.stderr.write(
            "ALTERED since it was committed to:\n  %s\n"
            "  A held record's verdict is fixed when it is issued and the\n"
            "  reply window cannot change it. Either that rule was broken or\n"
            "  the manifest is stale. If the edit was legitimate, say so in\n"
            "  the commit that updates the manifest, because the diff is the\n"
            "  only thing a stranger will have to judge it by.\n"
            % "\n  ".join(altered))
    if missing:
        sys.stderr.write(
            "COMMITTED TO BUT NOT ON DISK:\n  %s\n"
            "  A held record cannot be withdrawn by deleting the file.\n"
            % "\n  ".join(missing))
    if uncommitted:
        sys.stderr.write(
            "HELD BUT NOT COMMITTED TO:\n  %s\n"
            "  Nothing fixes this record's contents yet, so nothing would\n"
            "  show it being edited. Run: python3 suite/hold.py --commit\n"
            % "\n  ".join(uncommitted))
    # The three checks above compare the records against the manifest sitting
    # beside them. Both are writable by the same hand in the same minute, so
    # agreeing with each other establishes nothing on its own. What fixes a
    # verdict is the manifest in history.
    head = manifest_at_head()
    rewritten = rewritten_commitments(head, want)
    dropped = dropped_commitments(head, want)

    if rewritten:
        sys.stderr.write(
            "THE COMMITMENT ITSELF WAS REWRITTEN:\n")
        for name, was, now, wb, nb in rewritten:
            sys.stderr.write(
                "  %s\n    HEAD: %s bytes  %s\n    disk: %s bytes  %s\n"
                % (name, wb, (was or "")[:16], nb, (now or "")[:16]))
        sys.stderr.write(
            "  The record changed and the manifest changed with it, so the\n"
            "  two agree and this check would otherwise pass. A held record's\n"
            "  verdict is fixed when it is issued and the reply window cannot\n"
            "  change it, which is a claim about the manifest in history, not\n"
            "  about the copy on disk. If the edit was legitimate, commit the\n"
            "  manifest in a commit that says what changed and why. The diff\n"
            "  is the only thing a stranger will have to judge it by, and a\n"
            "  rewritten commitment with no explanation beside it reads as\n"
            "  the thing this gate exists to prevent.\n")
    if dropped:
        sys.stderr.write(
            "COMMITTED TO IN HEAD, NO LONGER IN THE MANIFEST:\n  %s\n"
            "  Dropping the entry is the quieter way to make an altered\n"
            "  record verify clean. A held file leaves the manifest when it\n"
            "  publishes, and then it is hashed in public.\n"
            % "\n  ".join(dropped))

    if altered or missing or uncommitted or rewritten or dropped:
        return 2
    if not quiet:
        if head is None:
            print("%d held file%s match the manifest on disk. git could not "
                  "read the\n  manifest at HEAD, so nothing here compared it "
                  "against a version\n  that cannot be rewritten. That is a "
                  "weaker check than it looks."
                  % (len(have), "" if len(have) == 1 else "s"))
        else:
            print("%d held file%s match the manifest, and the manifest "
                  "matches HEAD"
                  % (len(have), "" if len(have) == 1 else "s"))
    return 0


def held_ids_on_disk():
    """The ids of the held records, read from the records themselves."""
    ids = set()
    for name in held_names():
        if name.endswith(".json"):
            with io.open(os.path.join(HELD, name), encoding="utf-8") as fh:
                rid = json.load(fh).get("record_id")
            if rid:
                ids.add(rid)
    return ids


def held_ids_in_manifest():
    """The same ids, read from the manifest instead of from the records.

    The export has no records, so deriving the ids from disk there yields an
    empty set, and every disclosure check downstream searches for nothing and
    reports clean. A check that passes because it was handed nothing to look
    for is the exact failure this project grades others for, so the export
    reads its ids from the one file it does have. The manifest carries the ids
    on purpose: an id with no verdict attached is not a disclosure, which is
    why the register may state that a record is held and may not state what it
    found.
    """
    if not os.path.exists(MANIFEST):
        return set()
    with io.open(MANIFEST, encoding="utf-8") as fh:
        manifest = json.load(fh)
    return {r["record_id"] for r in manifest.get("held", [])
            if r.get("record_id")}


def disclosure_scan(ids):
    """What this repository would hand a stranger, given the ids to look for.

    Two questions, and the second is the one that has already been answered
    wrong here once: does any tracked file name a held record, and is any held
    record still reachable from a commit. Returns 0 or 2.
    """
    rc = 0
    tracked = git(["ls-files"])
    if tracked is not None:
        manifest_rel = os.path.relpath(MANIFEST, ROOT)
        bad = []
        for path in tracked.splitlines():
            if path == manifest_rel or not os.path.isfile(
                    os.path.join(ROOT, path)):
                continue
            try:
                with io.open(os.path.join(ROOT, path), encoding="utf-8",
                             errors="replace") as fh:
                    text = fh.read()
            except Exception:
                continue
            found = sorted(i for i in ids if i in text)
            if found:
                bad.append((path, found))
        if bad:
            rc = 2
            sys.stderr.write("TRACKED FILES NAMING A HELD RECORD:\n")
            for path, found in bad:
                sys.stderr.write("  %s: %s\n" % (path, ", ".join(found)))
            sys.stderr.write(
                "  The manifest is the one place a held id belongs, because\n"
                "  there it is labelled as a holding. Anywhere else it is an\n"
                "  identifier with no verdict attached, and the reader\n"
                "  supplies the verdict.\n")

    leaks = history_leaks(ids)
    if leaks:
        rc = 2
        sys.stderr.write(
            "HELD RECORDS ARE STILL IN THIS REPOSITORY'S HISTORY:\n")
        for rid in sorted(leaks):
            sys.stderr.write("  %s: %s\n" % (rid, ", ".join(sorted(leaks[rid]))))
        sys.stderr.write(
            "  Removing a file from the working tree does not remove it from\n"
            "  the commits that already carry it, and those commits are what\n"
            "  a clone hands over. Pushing this repository as it stands\n"
            "  publishes every held record in full, which ends the reply\n"
            "  window before it has opened.\n"
            "  Nothing here rewrites history on its own. That is a decision,\n"
            "  and the options are: rewrite the affected commits before the\n"
            "  first push, start the public repository from a fresh history,\n"
            "  or send the notices and wait out the windows so there is\n"
            "  nothing left to withhold.\n")
    elif leaks is not None:
        print("no held record is reachable from any commit")
    return rc


def cmd_audit():
    """Verify the hashes, then ask what this repository would hand a stranger."""
    rc = cmd_verify()
    return disclosure_scan(held_ids_on_disk()) or rc


# ------------------------------------------------------------------- the export
# The public repository is not this repository with fewer files in it. It has
# the opposite obligation: here a held record must be present and unaltered,
# and there it must be absent, so --verify passes on exactly the state that
# would be a disclosure and fails on exactly the state that is correct. Run in
# the export, all three checks the push hook makes fail, and they fail for a
# structural reason rather than a fixable one: the records it verifies are
# correctly missing, and the register it recompiles cannot be recompiled
# without them.
#
# The consequence was that the hook was installed nowhere. It could only work
# in the repository that has no remote and can never push, and it could never
# work in the one that pushes to the public. Its own opening line is that a
# push hands over the whole repository. It was sitting in the repository that
# does not push.
#
# That is the same shape as every other defect this project has found in
# itself: the guard was applied to the artifact it was written for, and to
# nothing else that discloses. So the export gets checks written for the
# export, and the mode is declared by the command rather than inferred from
# the directory, because a guard that guesses which repository it is in will
# eventually guess wrong and report clean.

_HELD_COUNT = re.compile(r"(\d+)\s+issued and held\b")


def register_held_count(text):
    """The number of held records the register states, or None.

    Pure, and separate from reading the file, so the parse can be exercised
    without one.
    """
    m = _HELD_COUNT.search(text)
    return int(m.group(1)) if m else None


def record_id_of(path):
    """The record_id a file on disk claims, or None if it does not claim one."""
    try:
        with io.open(path, encoding="utf-8") as fh:
            rid = json.load(fh).get("record_id")
    except Exception:
        return None
    return rid if isinstance(rid, str) and rid else None


def published_ids():
    """Record ids the register actually carries.

    The register is compiled from the records by the renderer, so an id on the
    page is an id that went through the publication gate. An id that is not on
    the page did not, whatever directory its file is sitting in.
    """
    if not os.path.exists(REGISTER):
        return set()
    try:
        with io.open(REGISTER, encoding="utf-8") as fh:
            page = fh.read()
    except Exception:
        return set()
    return set(re.findall(r"NBLX-\d{8}-\d{3}", page))


def cmd_verify_export():
    """Refuse a push from the public repository if it carries what it holds."""
    if not os.path.exists(MANIFEST):
        sys.stderr.write(
            "no %s. An export with no manifest commits to nothing, so the\n"
            "  register's claim that records are held is unbacked.\n"
            % os.path.relpath(MANIFEST, ROOT))
        return 2

    with io.open(MANIFEST, encoding="utf-8") as fh:
        manifest = json.load(fh)
    committed = {r["file"] for r in manifest.get("held", [])}
    rc = 0

    # 1. Absence, which is the inversion. Anything the manifest commits to is
    #    by definition adverse and unanswered, and here it is not evidence, it
    #    is the leak.
    # Every file in the held directory, not only the ones the manifest names.
    # This read `if n in committed`, which made it a filename allowlist run
    # backwards: the same held record copied to a .bak, or renamed by a hand
    # that was tidying, was reported as "none present" while sitting on disk.
    # The manifest is the commitment. The directory is the leak surface, and
    # in this repository it should be empty however a file got into it.
    present = sorted(held_names())

    # A .json in records/ is legitimate here exactly when the register
    # published it. This used to flag every one of them without asking, so the
    # first record this registry ever publishes would have refused every push
    # after it, and the only way past the leak guard on the day the first
    # finding went out would have been to switch it off. That is the same
    # defect this file already documents about the other hook, arriving at the
    # one moment the project exists for.
    published = published_ids()
    strays = []
    if os.path.isdir(RECORDS):
        for n in sorted(os.listdir(RECORDS)):
            if not n.endswith(".json") or n == os.path.basename(MANIFEST):
                continue
            rid = record_id_of(os.path.join(RECORDS, n))
            if rid and rid in published:
                continue
            strays.append(n)
    if present:
        rc = 2
        sys.stderr.write(
            "A HELD RECORD IS ON DISK IN THE PUBLIC REPOSITORY:\n  %s\n"
            "  In the working repository this state is correct and its\n"
            "  absence is the fault. Here it is reversed. Every file the\n"
            "  manifest commits to is a finding its subject has not answered\n"
            "  yet, and the export exists to carry the commitment without\n"
            "  carrying the finding.\n" % "\n  ".join(present))
    if strays:
        rc = 2
        sys.stderr.write(
            "RECORDS IN THE PUBLIC REPOSITORY THAT THE REGISTER DID NOT\n"
            "PUBLISH THROUGH THE RENDERER:\n  %s\n"
            "  A record reaches the public as a row on the register, which is\n"
            "  compiled. A record file that arrived here some other way came\n"
            "  by a path with no gate on it.\n" % "\n  ".join(strays))

    # 2. The count on the page and the count in the manifest are two copies of
    #    one fact, and they arrive here in two separate files. Copies drift,
    #    and a register that understates what is held is wrong in the
    #    direction nobody checks.
    if os.path.exists(REGISTER):
        with io.open(REGISTER, encoding="utf-8") as fh:
            stated = register_held_count(fh.read())
        want = sum(1 for r in manifest.get("held", [])
                   if str(r.get("file", "")).endswith(".json"))
        if stated is None:
            rc = 2
            sys.stderr.write(
                "THE REGISTER DOES NOT STATE HOW MANY RECORDS ARE HELD.\n"
                "  The one thing the disclosure rule permits this page to say\n"
                "  about a held record is that it exists and how many there\n"
                "  are. A page that has stopped saying it is either stale or\n"
                "  was edited by hand.\n")
        elif stated != want:
            rc = 2
            sys.stderr.write(
                "THE REGISTER AND THE MANIFEST DISAGREE:\n"
                "  the page states %d held, the manifest commits to %d.\n"
                "  Both were written by the renderer in the working\n"
                "  repository and copied here, so they disagreeing means one\n"
                "  of them came from a different build. Re-export both\n"
                "  together rather than correcting either one here; the copy\n"
                "  is output, and the records are the source.\n"
                % (stated, want))
    else:
        rc = 2
        sys.stderr.write(
            "NO %s.\n  The register is the product. Its absence is not a\n"
            "  clean state.\n" % os.path.relpath(REGISTER, ROOT))

    # 3. The scan that matters, with the ids taken from the manifest, since
    #    there are no records here to take them from.
    ids = held_ids_in_manifest()
    if not ids:
        rc = 2
        sys.stderr.write(
            "THE MANIFEST NAMES NO RECORD IDS.\n"
            "  Then the history walk below has nothing to search for and will\n"
            "  report clean whatever this repository contains.\n")
    rc = disclosure_scan(ids) or rc

    if rc == 0:
        print("export clean: %d held file%s committed to, none present, "
              "register agrees" % (len(committed),
                                   "" if len(committed) == 1 else "s"))
    return rc


def main(argv):
    if "--commit" in argv:
        return cmd_commit(amend="--amend" in argv)
    if "--verify-export" in argv:
        return cmd_verify_export()
    if "--audit" in argv:
        return cmd_audit()
    if "--verify" in argv:
        return cmd_verify()
    sys.stderr.write(__doc__.split("Usage:")[-1].strip() + "\n")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
