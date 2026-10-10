"""Two guards that could not fire, and the one that was never written.

Offline. A temporary tree and a stub git. Nothing in the real records
directory is read or written.

GIT UNUSABLE WAS CLASSIFIED AS ABSENT. git() returns None both when git
answered and the thing is not there, and when git could not run at all. Those
are opposite facts. With a `git` on PATH that exits 127, --verify-export
printed "no held record is reachable from any commit or named in a message"
and "export clean", exit 0, having read no commit, no ref and no tracked file.
The old guard could not catch it because the witness that we are in a
repository was computed with the same git that had just failed.

THE SAME CLASSIFICATION LET --commit OVERWRITE COMMITMENTS. manifest_in_head_state
returned "absent" when git failed, so head was None, rewritten_commitments and
dropped_commitments both came back empty, and every existing commitment was
rewritten with no refusal and no --amend.

held_by WENT INTO THE PUBLISHED MANIFEST AS FREE TEXT. render_register has a
guard for this exact string, and its docstring records the failure: "A held_by
of FAIL_UNSAFE published 'Gate: FAIL UNSAFE' on the public page and the build
exited 0." The renderer was hardened; the manifest writer, which produces the
one held artifact that is tracked and pushed, was not.
"""
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
HOLD = runpy.run_path(str(HERE / "hold.py"), run_name="hold_git_gate")
G = HOLD["git_state"].__globals__


class _StubGit:
    """A PATH whose `git` always fails, with python still reachable."""

    def __enter__(self):
        self.dir = tempfile.mkdtemp(prefix="nblx-nogit-")
        p = os.path.join(self.dir, "git")
        with io.open(p, "w", encoding="utf-8") as fh:
            fh.write("#!/bin/sh\nexit 127\n")
        os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)
        self.saved = os.environ.get("PATH", "")
        os.environ["PATH"] = self.dir + os.pathsep + self.saved
        return self

    def __exit__(self, *exc):
        os.environ["PATH"] = self.saved
        shutil.rmtree(self.dir, ignore_errors=True)
        return False


def _quiet(fn, *a):
    err, out = sys.stderr, sys.stdout
    sys.stderr = sys.stdout = io.StringIO()
    try:
        return fn(*a), sys.stdout.getvalue() + sys.stderr.getvalue()
    finally:
        sys.stderr, sys.stdout = err, out


class GitStateDiscriminates(unittest.TestCase):

    def test_a_working_git_in_a_repository_is_usable(self):
        self.assertEqual(HOLD["git_state"](), HOLD["GIT_USABLE"])

    def test_a_failing_git_is_unusable_not_absent(self):
        with _StubGit():
            self.assertEqual(HOLD["git_state"](), HOLD["GIT_UNUSABLE"])

    def test_unusable_is_not_the_same_token_as_no_repo(self):
        self.assertNotEqual(HOLD["GIT_UNUSABLE"], HOLD["GIT_NO_REPO"])


class TheScanRefusesRatherThanReportingClean(unittest.TestCase):

    def test_disclosure_scan_refuses_when_git_cannot_run(self):
        with _StubGit():
            rc, text = _quiet(HOLD["disclosure_scan"], ["NBLX-19990101-001"])
        self.assertEqual(rc, 2)
        self.assertIn("could not be run", text)

    def test_it_does_not_claim_a_clean_history(self):
        """The precise harm: a positive statement about every commit, made
        after reading none of them."""
        with _StubGit():
            _rc, text = _quiet(HOLD["disclosure_scan"], ["NBLX-19990101-001"])
        self.assertNotIn("no held record is reachable", text)

    def test_control_a_working_git_still_scans(self):
        """Without this the refusal above could be a scan that refuses always.

        The id must appear nowhere in the tree. The first draft used
        NBLX-00000000-000, which is fixture data in render_register.py and
        selftest.py, so the scan correctly flagged it and the control failed.
        The test data was wrong, not the scan.
        """
        rc, _text = _quiet(HOLD["disclosure_scan"], ["NBLX-17000101-777"])
        self.assertEqual(rc, 0)


class AnUnreadableCommitmentIsNotAnAbsentOne(unittest.TestCase):

    def test_head_state_is_unreadable_when_git_cannot_run(self):
        with _StubGit():
            state, head = HOLD["manifest_in_head_state"]()
        self.assertEqual(state, "unreadable")
        self.assertIsNone(head)

    def test_control_head_state_is_readable_normally(self):
        state, _head = HOLD["manifest_in_head_state"]()
        self.assertIn(state, ("ok", "absent"))


class TheManifestNamesGatesNotVerdicts(unittest.TestCase):

    def test_every_gate_the_runner_can_produce_is_accepted(self):
        for gate in ("right_of_reply", "subject_under_embargo", "unstated",
                     "HELD", "CLEARED", "PUBLISHED", "WITHDRAWN"):
            with self.subTest(gate=gate):
                self.assertEqual(
                    HOLD["_safe_gate"](gate, "x.json", "held_by"), gate)

    def test_a_verdict_class_is_refused(self):
        # The exact value the renderer's docstring says reached the public
        # page once already.
        for verdict in ("FAIL_UNSAFE", "FAIL_SAFE", "INDETERMINATE",
                        "OUT_OF_SCOPE", "PASS", "NOT_EVALUATED"):
            with self.subTest(verdict=verdict):
                with self.assertRaises(SystemExit):
                    HOLD["_safe_gate"](verdict, "x.json", "held_by")

    def test_free_text_naming_a_subject_is_refused(self):
        with self.assertRaises(SystemExit):
            HOLD["_safe_gate"]("adverse finding against acme-quotes-mcp",
                               "x.json", "held_by")

    def test_none_becomes_unstated_rather_than_raising(self):
        # A reply notice has no publication block at all, and that is ordinary.
        self.assertEqual(HOLD["_safe_gate"](None, "r.md", "held_by"),
                         "unstated")

    def test_a_non_string_is_refused_not_coerced(self):
        with self.assertRaises(SystemExit):
            HOLD["_safe_gate"]({"v": "right_of_reply"}, "x.json", "held_by")

    def test_surrounding_whitespace_is_tolerated(self):
        self.assertEqual(
            HOLD["_safe_gate"]("  right_of_reply  ", "x.json", "held_by"),
            "right_of_reply")


if __name__ == "__main__":
    unittest.main()
