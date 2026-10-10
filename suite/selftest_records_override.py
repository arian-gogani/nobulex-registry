"""The guards could not see the records they exist to protect.

Offline. A temporary records tree. The real records directory is never read or
written by this file.

The records live in a repository that deliberately has no remote, and the copy
of hold.py sitting beside them is hundreds of lines behind this one: zero of
the hardened-gate markers in this file appear in that one. So every guard added
here has been unable to reach the only records it was written for, while the
code that could reach them was the code without the guards. Copying either way
is forbidden, so the checks travel to the records instead.

A path override on a publication tool is itself a hazard, and the hazard is the
one this registry exists to find in other people's software: a command that can
be aimed at any directory is a command that can publish an embargoed finding
out of a tree nobody was watching. So the override reads and never writes, and
the refusal happens before any global moves, so a refused invocation cannot
leave the module half-aimed at somewhere else.

--check shares cmd_clear rather than reimplementing it. A separate checker
would be a second copy of the rule set, and a second copy of one rule with only
one of them fixed is the defect this suite has now found five times.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
HOLD = runpy.run_path(str(HERE / "hold.py"), run_name="hold_records_override")
main = HOLD["main"]
G = main.__globals__

_PATHS = ("ROOT", "RECORDS", "HELD", "MANIFEST", "REGISTER")


def _quiet(*argv):
    out, err = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = io.StringIO()
    try:
        rc = main(list(argv))
        return rc, sys.stdout.getvalue()
    finally:
        sys.stdout, sys.stderr = out, err


class _Tree:
    """A records tree holding one clearable record, globals restored after."""

    RECORD = {
        "record_id": "NBLX-19990102-001",
        "verdict": "FAIL_SAFE",
        "subject": {"package": "acme-quotes-mcp",
                    "execution_environment": {"resolved_dependencies": []}},
        "publication": {
            "status": "HELD",
            "held_by": "right_of_reply",
            "right_of_reply": {
                "required": True,
                "recipient": "maintainer of https://example.invalid/acme",
                "artifact_delivered_at": "1999-01-02T00:00:00Z",
                "window_days": 7,
                "window_closes_at": "1999-01-09T00:00:00Z",
                "reply_received_at": None,
                "reply": None}}}

    def __enter__(self):
        self.root = tempfile.mkdtemp(prefix="nblx-override-")
        held = os.path.join(self.root, "records", "held")
        os.makedirs(held)
        self.path = os.path.join(held, "NBLX-19990102-001.json")
        body = json.dumps(self.RECORD, indent=2)
        with io.open(self.path, "w", encoding="utf-8") as fh:
            fh.write(body)
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        with io.open(os.path.join(self.root, "records",
                                 "held.manifest.json"), "w",
                     encoding="utf-8") as fh:
            json.dump({"held": [{"file": "NBLX-19990102-001.json",
                                 "sha256": digest,
                                 "bytes": len(body)}]}, fh)
        self.digest = digest
        self.saved = {k: G[k] for k in _PATHS}
        return self

    def sha(self):
        with io.open(self.path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()

    def status(self):
        with io.open(self.path, encoding="utf-8") as fh:
            return json.load(fh)["publication"]["status"]

    def __exit__(self, *exc):
        G.update(self.saved)
        shutil.rmtree(self.root, ignore_errors=True)
        return False


class TheOverrideReadsTheOtherTree(unittest.TestCase):

    def test_check_reaches_a_record_in_another_root(self):
        with _Tree() as t:
            rc, out = _quiet("--records", t.root, "--check",
                             "NBLX-19990102-001")
            self.assertEqual(rc, 0, out)
            self.assertIn("WOULD CLEAR", out)

    def test_it_reports_the_committed_digest_it_matched(self):
        with _Tree() as t:
            _rc, out = _quiet("--records", t.root, "--check",
                              "NBLX-19990102-001")
            self.assertIn(t.digest, out)

    def test_a_path_with_no_records_held_is_refused(self):
        """And refused AS a bad path, not by falling back to this repository.

        An earlier version of this test asserted only the exit code, and a
        mutation that discarded the refusal survived it: a bad path left the
        globals pointing at the tree hold.py itself lives in, --check then
        answered "no record with that id" out of the wrong repository, and the
        exit code was 1 either way. Same number, opposite meaning. A typo in
        the path would have produced confident answers about a tree the user
        had not asked about, which is the fail-open shape this suite exists to
        catch.
        """
        empty = tempfile.mkdtemp(prefix="nblx-notatree-")
        try:
            saved = {k: G[k] for k in _PATHS}
            rc, out = _quiet("--records", empty, "--check", "X")
            self.assertEqual(rc, 1)
            self.assertIn("not a records tree", out)
            self.assertIn(empty, out)
            self.assertNotIn("no record with id", out)
            self.assertEqual({k: G[k] for k in _PATHS}, saved,
                             "a refused path must not move the globals")
        finally:
            shutil.rmtree(empty, ignore_errors=True)

    def test_records_without_a_path_is_refused(self):
        self.assertEqual(_quiet("--records")[0], 1)


class TheOverrideNeverWrites(unittest.TestCase):
    """The claim the docstring makes. If any of these regress, the override
    has become a way to publish out of an unwatched tree."""

    def test_clear_is_refused_with_an_overridden_root(self):
        with _Tree() as t:
            rc, _out = _quiet("--records", t.root, "--clear",
                              "NBLX-19990102-001")
            self.assertEqual(rc, 1)
            self.assertEqual(t.status(), "HELD")
            self.assertEqual(t.sha(), t.digest)

    def test_commit_is_refused_with_an_overridden_root(self):
        with _Tree() as t:
            rc, _out = _quiet("--records", t.root, "--commit")
            self.assertEqual(rc, 1)

    def test_a_refused_mutation_does_not_aim_the_globals(self):
        """It refuses before anything moves, so a later command in the same
        process cannot inherit a root the user was told was rejected."""
        with _Tree() as t:
            saved = {k: G[k] for k in _PATHS}
            _quiet("--records", t.root, "--clear", "NBLX-19990102-001")
            self.assertEqual({k: G[k] for k in _PATHS}, saved)

    def test_check_leaves_the_record_byte_identical(self):
        with _Tree() as t:
            before = t.sha()
            _quiet("--records", t.root, "--check", "NBLX-19990102-001")
            self.assertEqual(t.sha(), before)
            self.assertEqual(t.status(), "HELD")


class CheckIsTheSameRuleSetAsClear(unittest.TestCase):

    def test_an_open_reply_window_refuses_in_the_dry_run_too(self):
        with _Tree() as t:
            rec = dict(_Tree.RECORD)
            ror = dict(rec["publication"]["right_of_reply"])
            ror["window_closes_at"] = "2999-01-01T00:00:00Z"
            rec["publication"] = dict(rec["publication"])
            rec["publication"]["right_of_reply"] = ror
            with io.open(t.path, "w", encoding="utf-8") as fh:
                json.dump(rec, fh, indent=2)
            rc, _out = _quiet("--records", t.root, "--check",
                              "NBLX-19990102-001")
            self.assertEqual(rc, 1)

    def test_the_misnamed_subject_refuses_in_the_dry_run_too(self):
        with _Tree() as t:
            rec = json.loads(json.dumps(_Tree.RECORD))
            rec["subject"]["package"] = "subj"
            rec["subject"]["execution_environment"]["resolved_dependencies"] \
                = ["acme-quotes-mcp @ file:///tmp/build/subj"]
            with io.open(t.path, "w", encoding="utf-8") as fh:
                json.dump(rec, fh, indent=2)
            rc, _out = _quiet("--records", t.root, "--check",
                              "NBLX-19990102-001")
            self.assertEqual(rc, 1)

    def test_check_without_an_id_is_refused(self):
        self.assertEqual(_quiet("--check")[0], 1)

    def test_an_unknown_id_is_refused_not_silently_clean(self):
        with _Tree() as t:
            rc, _out = _quiet("--records", t.root, "--check",
                              "NBLX-19990102-999")
            self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
