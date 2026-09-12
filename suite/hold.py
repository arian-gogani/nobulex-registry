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
        python3 suite/hold.py --clear RECORD-ID
                                         (open the gate on one record, by name,
                                          after its obligation is discharged)
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


def blobs_in_history():
    """Every blob reachable from any ref, as {object id: one path it had}.

    Deduped by object id, so a file that never changed is read once instead of
    once per commit, and `rev-list --all` rather than HEAD, because a branch
    nobody has merged is still a branch somebody can push.
    """
    revs = git(["rev-list", "--all"])
    if revs is None:
        return None
    seen = {}
    for rev in revs.split():
        listing = git(["ls-tree", "-r", rev]) or ""
        for line in listing.splitlines():
            meta, _, path = line.partition("\t")
            bits = meta.split()
            if len(bits) < 3 or bits[1] != "blob":
                continue
            seen.setdefault(bits[2], path)
    return seen


def history_leaks(ids, held_files=()):
    """Held content reachable from a commit in this repo.

    Moving the records out of git protects the next push and does nothing at
    all about the commits that already carry them, and those commits are
    exactly what a clone hands over.

    This used to read only `records/**.json`, parse each one, and match a
    top-level record_id. Three things walked past it, all of them tested for
    below and all of them a full disclosure of a record whose subject has not
    answered it:

      - the reply notice, which is a .md and never had a .json suffix to match
      - the record committed anywhere other than records/
      - the record pasted into a write-up, which is the shape that put
        docs/outreach on the public site in the first place

    Meanwhile the check printed "no held record is reachable from any commit",
    which is a statement about the repository, not about records/*.json.

    Every blob now gets read and searched for the held ids as text, and any
    path whose basename is a file the manifest commits to is a hit on its name
    alone, since the manifest names the reply documents that carry no id. The
    manifest itself is skipped: an id belongs there, labelled as a holding.

    Nothing found inside a blob is printed, returned or stored. The paths and
    the ids come back; the contents do not.
    """
    blobs = blobs_in_history()
    if blobs is None:
        return None
    manifest_name = os.path.basename(MANIFEST)
    wanted = set(held_files or ())
    ids = [i for i in ids if i]
    hits = {}
    for oid, path in blobs.items():
        base = os.path.basename(path)
        if base == manifest_name:
            continue
        if base in wanted:
            hits.setdefault(base, set()).add(path)
            continue
        if not ids:
            continue
        # Read it whole. A size cap here would be an input skipped and counted
        # as agreement, which is the defect this suite grades other people on,
        # and a pasted record hides in a large file rather than a small one.
        blob = git(["cat-file", "-p", oid])
        if not blob:
            continue
        for rid in ids:
            if rid in blob:
                hits.setdefault(rid, set()).add(path)
    return hits


MANIFEST_PURPOSE = (
    "Each entry commits to one held file by sha256 without disclosing what it "
    "says. When the file publishes, hash it and compare: equal means the "
    "record was not altered while its subject held the right to answer it. "
    "The subject is deliberately absent, because a record held under right of "
    "reply is adverse by definition, and naming who it is about would publish "
    "the accusation while withholding the evidence for it.")


def manifest_in_head_state(rev="HEAD"):
    """Whether `rev` carries a readable manifest: 'absent', 'unreadable', 'ok'.

    Three states, not two. A repository whose first commit has not happened,
    or which has never committed a manifest, is ABSENT: there is no
    commitment yet and making one is the ordinary case. A manifest that is
    present in HEAD and does not parse, or whose held is not a list, is
    UNREADABLE: a commitment exists and cannot be checked, which is not a
    licence to overwrite it.

    Collapsing those two into None made the first commit refuse.

    `rev` defaults to HEAD and every existing caller leaves it there. It is a
    parameter so that first_commitments() below can ask the same question of
    an older commit without a second copy of this three-way answer, which is
    the kind of duplicate that drifts apart and then disagrees in the one
    case nobody tested.
    """
    rel = os.path.relpath(MANIFEST, ROOT).replace(os.sep, "/")
    blob = git(["show", "%s:%s" % (rev, rel)])
    if blob is None:
        return "absent", None
    try:
        m = json.loads(blob)
    except ValueError:
        return "unreadable", None
    if not isinstance(m, dict) or not isinstance(m.get("held"), list):
        return "unreadable", None
    return "ok", {r["file"]: r for r in m["held"]
                  if isinstance(r, dict) and r.get("file")}


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
    # `held` has to be a list, and this is not pedantry about types. Nothing
    # checked it, so a manifest whose held was an object keyed by filename
    # (same information, same hashes, valid JSON, correct schema string)
    # produced {} here, which is indistinguishable from an empty manifest and
    # is not None, so every caller took the strong branch.
    #
    # Verified end to end: with that manifest in HEAD, a verdict on disk was
    # flipped from adverse to clean, --commit did NOT refuse (its refusal
    # iterates head.items(), which was empty), --amend was never needed, and
    # --verify printed "the manifest matches HEAD" about a manifest it had
    # failed to parse. The refusal exists so a rewrite has to appear in shell
    # history; this path removed the trace along with the check.
    #
    # None means git or the manifest could not answer, which the callers
    # already announce as a weaker check. That is the honest state here.
    held = m.get("held")
    if not isinstance(held, list):
        return None
    return {r["file"]: r for r in held
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


def commitments_not_in_head(head, disk):
    """Entries the manifest on disk carries that HEAD does not commit to.

    The inverse of dropped_commitments, and the hole it leaves open is
    larger. Every comparison in this file iterated the HEAD side, so an entry
    HEAD had never seen was never visited by anything: not by
    rewritten_commitments, which reads head.items(), and not by
    dropped_commitments, which subtracts disk from head. A record added to
    the manifest and not yet committed could therefore be edited and
    re-committed without limit, with no --amend asked for and no git commit
    run, and --verify printed "the manifest matches HEAD" every time.

    Reproduced before this was written: a second held record was added, the
    manifest was written by --commit and deliberately not committed, and the
    record's verdict was then rewritten three times in a row. --commit exited
    0 on each rewrite without ever asking for --amend, --verify exited 0 on
    each, and HEAD still listed one file while --verify said two matched it.

    head is None means git could not answer or the committed manifest could
    not be read. That is not the same fact as HEAD answering that it commits
    to nothing, and reporting every entry as uncommitted on the strength of
    it would turn an unreadable repository into a wall of accusations. The
    callers announce that weaker state separately, so this returns nothing.
    """
    if head is None:
        return []
    return sorted(set(disk or {}) - set(head))


def commitment_commits():
    """Every commit that changed the manifest, oldest first, or None.

    A pathspec makes git list only the commits where the file differs from
    its parent, so this is one entry per version of the manifest rather than
    one per commit in the repository. None when git cannot answer, which
    includes a repository whose first commit has not happened.
    """
    rel = os.path.relpath(MANIFEST, ROOT).replace(os.sep, "/")
    log = git(["log", "--format=%H", "--", rel])
    if log is None:
        return None
    return list(reversed(log.split()))


def first_commitments():
    """The earliest commitment history carries for each file.

    Returns (state, {file: {sha256, bytes, commit}}) with the same three
    states manifest_in_head_state uses, because it is what reads each commit.

    Why the earliest and not HEAD's. Every check here compared against
    `git show HEAD:records/held.manifest.json`, and HEAD is the tip rather
    than the history. The same hand that edits a record can move the tip:
    flip a verdict, run --commit --amend, run `git commit --amend
    --no-edit`, and --verify goes green with one commit in the log and the
    hash that was committed on the day the record was issued gone from the
    reachable object graph. That sequence was run before this was written and
    it printed "1 held file match the manifest, and the manifest matches
    HEAD" over a verdict that had been flipped from FAIL to PASS.

    Walking to the earliest narrows that window and does not close it, and
    the difference matters enough to say plainly rather than to imply. An
    amended tip only destroys the tip's version of the manifest. A
    commitment made in some earlier commit survives it and is found here,
    so the rewrite is caught. A commitment whose only version lives in the
    tip commit is destroyed along with it, and nothing inside the repository
    can catch that, because the evidence it would be caught by is what the
    amend deleted. Confirmed by running exactly that: with one commit in the
    log, this walk returns the rewritten manifest as the earliest one and
    finds no divergence at all.

    So cmd_verify also says out loud when the commitment it is relying on
    was introduced by the tip, since a tip is one `git commit --amend` from
    gone. An external anchor is the only thing that fixes the remainder, and
    the module docstring already lists it as a stated gap.

    Cost: one `git log` plus one `git show` per version of the manifest, on
    every --verify. That is seven subprocesses on this repository today and
    it grows with the number of times the manifest has changed, not with the
    number of commits. --audit already reads every blob reachable from every
    ref, so this is not the expensive thing in the file. No cap on the walk:
    a cap here would be a commitment skipped and counted as agreement, which
    is the defect this suite grades other people on.
    """
    commits = commitment_commits()
    if commits is None:
        return "absent", None
    first = {}
    seen_unreadable = False
    for sha in commits:
        state, held = manifest_in_head_state(sha)
        if state != "ok":
            seen_unreadable = seen_unreadable or state == "unreadable"
            continue
        for name, row in held.items():
            if name not in first:
                first[name] = {"sha256": row.get("sha256"),
                               "bytes": row.get("bytes"), "commit": sha}
    if not first:
        return ("unreadable" if seen_unreadable else "absent"), None
    return "ok", first


def rewritten_since_first(first, disk):
    """Entries whose sha256 differs from the earliest commitment rather than
    from HEAD's. Returns [(file, was, now, was_bytes, now_bytes, commit)].

    The comparison itself is rewritten_commitments, unchanged, because the
    question is the same one and two copies of it would eventually answer
    differently. All this adds is the commit that introduced the value being
    compared against, so the report names something a stranger can go and
    read instead of asserting that a rewrite happened.

    A file that has left the manifest is not reported here. It is dropped,
    not rewritten, and dropping is what publication looks like: the record
    moves to records/ and is hashed in public from then on.
    """
    return [(name, was, now, wb, nb, (first or {})[name].get("commit"))
            for name, was, now, wb, nb
            in rewritten_commitments(first, disk)]


def published_out_of_hold(names):
    """Of `names`, the ones that left the hold by publishing.

    A held file is allowed to leave the manifest, and there is exactly one
    way that happens legitimately: --clear moves the record out of
    records/held/ and into records/, where it is a tracked file that the
    register renders and that anyone can hash. So a dropped entry whose file
    is now sitting in records/ is the ordinary end of a hold, and a dropped
    entry whose file is simply gone is the quiet edit dropped_commitments
    warns about.

    This is not a way around the refusal. Putting the record in records/ to
    make the drop acceptable publishes it, and cmd_verify_export already
    refuses a record file the register never published.
    """
    return [n for n in names
            if os.path.isfile(os.path.join(RECORDS, n))]


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
    # head is None means the committed manifest could not be read: git did not
    # answer, or the JSON was not a manifest, or its held was not a list.
    # Whatever the cause, there is nothing to compare against, so the refusal
    # below cannot fire and every existing commitment can be overwritten in
    # silence. Verified: with a manifest in HEAD whose held was an object
    # rather than a list, a verdict on disk was flipped and --commit rewrote
    # the manifest and exited 0, no --amend asked for, nothing in the shell
    # history to show it. The refusal exists precisely to leave that trace.
    #
    # An unreadable commitment is not an absent one, and it is not a licence
    # to replace it.
    state, _ = manifest_in_head_state()
    if state == "unreadable" and not amend:
        sys.stderr.write(
            "REFUSED: the manifest in HEAD could not be read, so this "
            "command cannot tell a new commitment from a rewritten one.\n"
            "  Nothing was written. Either git could not answer, or the\n"
            "  committed manifest is not shaped like a manifest. Both mean\n"
            "  the commitments already in history cannot be checked against\n"
            "  what is on disk, and writing over them would replace them\n"
            "  without ever showing what was replaced. Fix the manifest in\n"
            "  HEAD, or if this is deliberate re-run with --amend and say\n"
            "  in the commit message what changed and why.\n")
        return 2
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
    # Refusing the rewrite and permitting the drop refuses nothing, because
    # two calls do what one call is stopped from doing. Move the record out
    # of records/held/, run --commit, and this command cheerfully writes a
    # manifest with the entry gone: rewritten_commitments skips it, since its
    # `now` is None, and dropped_commitments knew about it and was never
    # asked. Commit that manifest, put back an edited record, run --commit
    # again, and the entry looks new rather than rewritten, so nothing
    # refuses. Verified end to end: a verdict went from FAIL to PASS, the
    # committed hash changed, --verify finished green, and --amend was never
    # typed once.
    #
    # dropped_commitments' own docstring called this "the other way to make
    # an altered record verify clean" and only --verify was consulting it.
    # A file that published is not this: it left the hold through --clear and
    # is in records/ being hashed in public.
    dropping = dropped_commitments(head, fresh)
    published = set(published_out_of_hold(dropping))
    would_drop = [n for n in dropping if n not in published]
    if would_drop and not amend:
        sys.stderr.write("REFUSED: this would drop a commitment already in "
                         "HEAD.\n")
        for name in would_drop:
            sys.stderr.write("  %s\n    HEAD: %s bytes  %s\n    disk: no "
                             "entry, and no file in records/\n"
                             % (name, head[name].get("bytes"),
                                (head[name].get("sha256") or "")[:16]))
        sys.stderr.write(
            "  Nothing was written. Deleting the line is the quieter way to\n"
            "  make an altered record verify clean, and it is quieter\n"
            "  precisely because the hash never changes: it stops existing.\n"
            "  A held file leaves the manifest when it publishes, and then\n"
            "  it is in records/ where anyone can hash it. If this record is\n"
            "  meant to be withdrawn rather than published, re-run with\n"
            "  --amend and say in the commit message what was withdrawn and\n"
            "  why, because the diff is the only thing a stranger will have\n"
            "  to judge it by.\n")
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
    #
    # manifest_in_head_state returns the same map manifest_at_head does, and
    # also says which of the three states produced it, which the check below
    # needs: an entry missing from HEAD because HEAD has no readable manifest
    # is a different fact from an entry missing from a manifest HEAD can read.
    head_state, head = manifest_in_head_state()
    rewritten = rewritten_commitments(head, want)
    dropped = dropped_commitments(head, want)
    uncommitted_entries = commitments_not_in_head(head, want)
    first_state, first = first_commitments()
    since_first = rewritten_since_first(first, want)

    # Both of the above were computed and discarded, which made this the most
    # expensive kind of dead code: the docstring on first_commitments explains
    # at length why HEAD alone is not enough, and nothing acted on the answer.
    #
    # rewritten_commitments asks whether disk disagrees with HEAD. The same
    # hand can edit a record, run --commit, and amend the tip, after which
    # HEAD and disk agree and that check goes quiet forever. The commitment
    # that cannot be amended away is the earliest one in history, which is
    # what first_commitments finds and what this compares against.
    #
    # Reported separately from the HEAD check and after it, because the two
    # say different things. HEAD disagreeing is an edit that has not been
    # committed yet. The first commitment disagreeing is an edit that has
    # already been papered over, and it is the one a stranger auditing this
    # repository would care about.
    if since_first and not any(n == m for n, _, _, _, _ in rewritten
                               for m, _, _, _, _, _ in since_first):
        sys.stderr.write(
            "\nTHE ORIGINAL COMMITMENT DISAGREES:\n")
        for name, was, now, wb, nb, commit in since_first:
            sys.stderr.write(
                "  %s\n    first committed in %s: %s bytes  %s\n"
                "    on disk now:              %s bytes  %s\n"
                % (name, (commit or "?")[:12], wb, (was or "")[:16],
                   nb, (now or "")[:16]))
        sys.stderr.write(
            "  HEAD and the working copy agree, so the check above stayed\n"
            "  quiet. They agree because both changed. This compares against\n"
            "  the first commit that ever carried a hash for this file, which\n"
            "  no later amend can reach. If the edit was legitimate, the\n"
            "  commit that made it is the explanation, and the sha above is\n"
            "  the thing to explain.\n")
        return 2

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


def message_leaks(ids):
    """Held ids named in a commit message.

    A commit message travels with the commit and is published with it. The
    other two checks read what a tracked file says and what a blob in history
    says, and a message is neither, so a commit that announces which record it
    is holding walked the id straight past a scan whose whole job is to stop
    that.

    Not hypothetical. "record: hold <id>, and make the runner declare the gate
    holding it" is the natural way to write the commit that issues a record,
    and it is how one already reads in the working repository. That repository
    has no remote, which is the only reason it is not a disclosure.

    Returns {record_id: {commit sha}}. Never the message text.
    """
    ids = [i for i in ids if i]
    if not ids:
        return {}
    out = git(["log", "--all", "--format=%x1e%H%x1f%B"])
    if out is None:
        return None
    hits = {}
    for chunk in out.split("\x1e"):
        if not chunk.strip():
            continue
        sha, _, body = chunk.partition("\x1f")
        for rid in ids:
            if rid in body:
                hits.setdefault(rid, set()).add(sha.strip()[:12])
    return hits


def held_files_in_manifest():
    """The file names the manifest commits to, records and reply documents.

    The reply documents carry no record_id, so ids alone cannot find them, and
    a notice naming the subject and the finding is not less of a disclosure
    than the record it accompanies.
    """
    if not os.path.exists(MANIFEST):
        return set()
    try:
        with io.open(MANIFEST, encoding="utf-8") as fh:
            manifest = json.load(fh)
    except (IOError, OSError, ValueError):
        return set()
    if not isinstance(manifest, dict):
        return set()
    return {r["file"] for r in manifest.get("held", [])
            if isinstance(r, dict) and r.get("file")}


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

    leaks = history_leaks(ids, held_files_in_manifest())
    if leaks:
        rc = 2
        sys.stderr.write(
            "HELD CONTENT IS STILL IN THIS REPOSITORY'S HISTORY:\n")
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
    said = message_leaks(ids)
    if said:
        rc = 2
        sys.stderr.write("COMMIT MESSAGES NAMING A HELD RECORD:\n")
        for rid in sorted(said):
            sys.stderr.write("  %s: %s\n" % (rid, ", ".join(sorted(said[rid]))))
        sys.stderr.write(
            "  A message is published with its commit. Naming the record a\n"
            "  commit holds is the natural way to write it and it puts the\n"
            "  identifier in front of every reader with no verdict attached,\n"
            "  which is the same disclosure as a tracked file naming one.\n"
            "  Rewriting a message rewrites the commit, so this is a decision\n"
            "  and not a cleanup: amend before the first push, or start the\n"
            "  public history fresh, which is what was done here.\n")

    # Fail closed when a scan could not run. Suppressing the clean sentence
    # was not enough: rc was left at 0, so the caller printed its own louder
    # summary and the suppression was cosmetic. Verified: with a full leak in
    # a tracked file and no .git anywhere, every scan returned None and
    # --verify-export printed "export clean" and exited 0.
    #
    # An empty id set is the same failure in a different costume.
    # message_leaks returns {} without spawning git when ids is empty, and {}
    # is falsy and not None, so the clean line was printed for a scan that
    # never ran. cmd_verify_export guards for this; cmd_audit did not, and a
    # held set consisting only of reply notices carries no ids at all.
    #
    # "Could not answer" and "answered no" are different facts. This file
    # already says so in manifest_at_head's docstring.
    # Not a git repository at all is a different fact from git refusing to
    # answer. With no repository nothing is tracked and no commit exists, so
    # those two scans are vacuous rather than failed and there is nothing for
    # a clone to carry, because there is nothing to clone. Inside a
    # repository, a scan that returns None looked at nothing and must not be
    # reported as having found nothing.
    in_repo = git(["rev-parse", "--git-dir"]) is not None
    unran = [n for n, v in (("tracked files", tracked),
                            ("history", leaks),
                            ("commit messages", said)) if v is None]
    if unran and in_repo:
        sys.stderr.write(
            "THE DISCLOSURE SCAN COULD NOT RUN:\n"
            "  no answer from: %s\n"
            "  This is not a clean result. git could not be read, so nothing\n"
            "  was established about what this repository would hand a\n"
            "  stranger. A scan that could not look is reported as a failure\n"
            "  rather than as a finding of nothing.\n" % ", ".join(unran))
        return 2
    # No ids AND nothing held is the ordinary empty state, and it is clean.
    # No ids WHILE something is held is the dangerous one: every check below
    # returns empty without looking, and a held set made only of reply notices
    # produces no identifiers at all, while the notices are the files that
    # carry the finding in full.
    if not ids and held_files_in_manifest():
        sys.stderr.write(
            "THE DISCLOSURE SCAN HAD NOTHING TO SEARCH FOR:\n"
            "  the manifest commits to files but supplied no record\n"
            "  identifiers, so every check below returned empty without\n"
            "  looking. A held set consisting only of reply notices produces\n"
            "  no identifiers, and the notices are the files that carry the\n"
            "  finding in full.\n")
        return 2

    if not leaks and not said:
        print("no held record is reachable from any commit or named in a "
              "message")
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
        # os.walk, not os.listdir. This read one directory deep, so a record
        # the renderer never published was invisible one level down and mkdir
        # was the entire exploit. Verified: an unpublished adverse record
        # naming a third party, committed at records/drafts/, returned
        # "export clean" and exit 0, while the same file at the top level was
        # caught. It has no backstop either, because a record the manifest
        # does not list contributes no id for the disclosure scan to look for.
        held_dir = os.path.abspath(HELD)
        for dirpath, dirnames, filenames in os.walk(RECORDS):
            if os.path.abspath(dirpath) == held_dir:
                # The held directory has its own check above, which reports
                # presence rather than publication. Walking it here would
                # double-report every held file.
                dirnames[:] = []
                continue
            for n in sorted(filenames):
                if not n.endswith(".json") or n == os.path.basename(MANIFEST):
                    continue
                full = os.path.join(dirpath, n)
                rid = record_id_of(full)
                if rid and rid in published:
                    continue
                strays.append(os.path.relpath(full, RECORDS))
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


CLEARED_STATUS = "CLEARED"
# render_register.py publishes a record only when its publication status is one
# of these. It is deliberately a short list and deliberately does not include
# PUBLISHABLE, the status run.py writes for a non-adverse verdict, because a
# verdict the harness liked is not the same event as a person deciding to
# publish it. That distinction is the entire reason the gate exists.
RENDERER_ACCEPTS = ("CLEARED", "PUBLISHED")


def _record_paths():
    """Every record file, held or not, by record_id.

    Both directories, because a non-adverse record is written straight to
    records/ by the runner while an adverse one is filed under records/held/,
    and clearing has to find either. Which directory a file sits in is a fact
    about storage. Whether it may publish is a fact about its publication
    block, and only that block is consulted below.
    """
    found = {}
    for d in (RECORDS, HELD):
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if not name.endswith(".json") or name.endswith(".manifest.json"):
                continue
            path = os.path.join(d, name)
            if not os.path.isfile(path):
                continue
            try:
                with io.open(path, encoding="utf-8") as fh:
                    rec = json.load(fh)
            except ValueError:
                continue
            rid = rec.get("record_id")
            if rid:
                found[rid] = (path, rec)
    return found


def _reply_obligation_unmet(rec):
    """Why this record may not publish yet, or None if nothing blocks it.

    The rule this enforces is the one in the record's own right_of_reply block:
    an adverse finding reaches its subject before it reaches the public, and
    the subject gets the full window to answer. A record that never went out
    has not satisfied that by waiting, because nothing was ever sent. Silence
    from someone who was never written to is not silence, it is absence.
    """
    pub = rec.get("publication") or {}
    ror = pub.get("right_of_reply") or {}
    if not ror.get("required"):
        return None
    if not ror.get("artifact_delivered_at"):
        return ("the artifact was never delivered, so the window never "
                "opened. Deliver it, record artifact_delivered_at and "
                "window_closes_at, then clear.")
    closes = ror.get("window_closes_at")
    if not closes:
        return ("delivered, but window_closes_at is unset, so there is no "
                "stated deadline this record can be past.")
    from datetime import datetime, timezone
    try:
        deadline = datetime.fromisoformat(str(closes).replace("Z", "+00:00"))
    except ValueError:
        return "window_closes_at is not a readable timestamp: %r" % (closes,)
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if now < deadline and not ror.get("reply_received_at"):
        return ("the reply window is still open until %s and no reply has "
                "arrived. Publishing now would take the window back."
                % deadline.isoformat())
    return None


def cmd_clear(record_id):
    """Open the gate on exactly one record, named on the command line.

    There is no --all and no globbing, on purpose. Publication is the one
    irreversible thing this registry does: a verdict about a named third party
    goes in front of the public, and no later edit unpublishes what was read.
    An operation like that should cost one deliberate invocation per record and
    should appear in shell history with the record's own identifier in it.

    This command does not decide anything. It records that a person decided,
    and it refuses when the record's stated obligation to its subject has not
    actually been discharged.
    """
    found = _record_paths()
    if record_id not in found:
        sys.stderr.write("REFUSED: no record with id %s under records/ or "
                         "records/held/.\n" % record_id)
        if found:
            sys.stderr.write("  present: %s\n" % ", ".join(sorted(found)))
        return 1

    path, rec = found[record_id]
    pub = rec.get("publication") or {}
    status = (pub.get("status") or "").strip().upper()

    if status in RENDERER_ACCEPTS:
        sys.stderr.write("REFUSED: %s is already %s. Nothing to do.\n"
                         % (record_id, status))
        return 1

    if (rec.get("status") or "").upper() == "WITHDRAWN":
        sys.stderr.write("REFUSED: %s is withdrawn. A withdrawn record is not "
                         "republished, it stays withdrawn and the withdrawal "
                         "is the public fact.\n" % record_id)
        return 1

    blocked = _reply_obligation_unmet(rec)
    if blocked:
        sys.stderr.write("REFUSED: %s cannot clear yet.\n  %s\n"
                         % (record_id, blocked))
        return 1

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    pub["status"] = CLEARED_STATUS
    pub["cleared_at"] = now.isoformat()
    pub["cleared_from"] = status or "unstated"
    rec["publication"] = pub

    # The validity clock starts here, not at observation. An adverse record
    # spends an unbounded stretch between being observed and being cleared,
    # because delivery and the reply window are human-paced. Dating the window
    # from the run is what left earlier records expired before anyone could
    # have read them. See _validity_block in suite/run.py.
    val = rec.get("validity") or {}
    if not val.get("until"):
        from datetime import timedelta
        val["from"] = now.isoformat()
        val["until"] = (now + timedelta(days=7)).isoformat()
        val["note"] = ("Queried outside this window the record returns "
                       "EXPIRED regardless of verdict. The window starts at "
                       "clearing, not at observation, because the record was "
                       "not readable by anyone before it cleared.")
        rec["validity"] = val

    with io.open(path, "w", encoding="utf-8") as fh:
        json.dump(rec, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    moved_to = path
    if os.path.dirname(os.path.abspath(path)) == os.path.abspath(HELD):
        dest = os.path.join(RECORDS, os.path.basename(path))
        os.rename(path, dest)
        moved_to = dest

    print("CLEARED  %s" % record_id)
    print("  status   %s -> %s" % (pub["cleared_from"], CLEARED_STATUS))
    print("  valid    %s .. %s" % (rec["validity"].get("from"),
                                   rec["validity"].get("until")))
    print("  file     %s" % os.path.relpath(moved_to, ROOT))
    print()
    print("This record is now publishable and nothing has published it yet.")
    print("Next, in order:")
    print("  python3 suite/hold.py --commit      (the held set changed)")
    print("  python3 suite/render_register.py    (rebuild the page)")
    return 0


def main(argv):
    if "--clear" in argv:
        i = argv.index("--clear")
        if i + 1 >= len(argv):
            sys.stderr.write("REFUSED: --clear needs a record id, by name.\n")
            return 1
        return cmd_clear(argv[i + 1])
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
