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

Usage:  python3 suite/hold.py --commit   (write the manifest from the records)
        python3 suite/hold.py --verify   (fail if a held record was altered)
        python3 suite/hold.py --audit    (also search git for leaked content)
"""
import hashlib
import io
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HELD = os.path.join(ROOT, "records", "held")
MANIFEST = os.path.join(ROOT, "records", "held.manifest.json")


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


def cmd_commit():
    names = held_names()
    manifest = {
        "schema": "nobulex.held.manifest.v0",
        "purpose": MANIFEST_PURPOSE,
        "held_count": len(names),
        "held": [entry(n) for n in names],
    }
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
    if altered or missing or uncommitted:
        return 2
    if not quiet:
        print("%d held file%s, all matching the committed hashes"
              % (len(have), "" if len(have) == 1 else "s"))
    return 0


def cmd_audit():
    """Verify the hashes, then ask what this repository would hand a stranger."""
    rc = cmd_verify()
    ids = set()
    for name in held_names():
        if name.endswith(".json"):
            with io.open(os.path.join(HELD, name), encoding="utf-8") as fh:
                rid = json.load(fh).get("record_id")
            if rid:
                ids.add(rid)

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


def main(argv):
    if "--commit" in argv:
        return cmd_commit()
    if "--audit" in argv:
        return cmd_audit()
    if "--verify" in argv:
        return cmd_verify()
    sys.stderr.write(__doc__.split("Usage:")[-1].strip() + "\n")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
