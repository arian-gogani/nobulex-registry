"""Offline regression: --verify must not cry wolf in the export repository.

No network, no git operations against the real tree. hold.py's module globals
are pointed at a temporary directory and restored afterwards.

The distinction under test: EVERY committed record absent is the export
repository's correct state and the wrong command being run. SOME absent is a
real integrity failure in either tree. Before this, --verify treated both the
same and printed "A held record cannot be withdrawn by deleting the file" over
all seven files on a repository where --verify-export exits 0 and reports
"none present, register agrees".

A confident false alarm is worse than no alarm in a tool whose only job is
raising true ones, because the reader cannot distinguish it from the real
thing and learns to discount the next one.
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
sys.path.insert(0, str(HERE))
hold = runpy.run_path(str(HERE / "hold.py"), run_name="hold_wrong_repo_regression")
cmd_verify = hold["cmd_verify"]


class _Tree:
    """A throwaway records tree, with hold.py's globals aimed at it."""

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="nblx-wrongrepo-")
        self.held = os.path.join(self.root, "records", "held")
        os.makedirs(self.held)
        self.manifest = os.path.join(self.root, "records", "held.manifest.json")
        self._saved = None

    def write(self, name, body):
        p = os.path.join(self.held, name)
        with io.open(p, "w", encoding="utf-8") as fh:
            fh.write(body)
        return hashlib.sha256(body.encode("utf-8")).hexdigest()

    def commit(self, entries):
        """entries: {filename: sha256}. Written as the manifest, no git."""
        with io.open(self.manifest, "w", encoding="utf-8") as fh:
            json.dump({"held": [{"file": n, "sha256": s, "bytes": 1}
                                for n, s in sorted(entries.items())]}, fh)

    def remove(self, name):
        os.remove(os.path.join(self.held, name))

    def __enter__(self):
        import builtins  # noqa: F401  (kept explicit: we only touch hold's globals)
        self._saved = (hold["ROOT"], hold["RECORDS"], hold["HELD"],
                       hold["MANIFEST"])
        # cmd_verify closes over module globals, so they are what must move.
        g = cmd_verify.__globals__
        g["ROOT"] = self.root
        g["RECORDS"] = os.path.join(self.root, "records")
        g["HELD"] = self.held
        g["MANIFEST"] = self.manifest
        return self

    def __exit__(self, *exc):
        g = cmd_verify.__globals__
        (g["ROOT"], g["RECORDS"], g["HELD"], g["MANIFEST"]) = self._saved
        shutil.rmtree(self.root, ignore_errors=True)
        return False


def verify_with(stderr_to):
    """cmd_verify's exit code, with stderr captured into stderr_to."""
    real = sys.stderr
    sys.stderr = stderr_to
    try:
        return cmd_verify()
    finally:
        sys.stderr = real


class WrongRepoGuard(unittest.TestCase):

    def test_all_records_absent_names_the_other_command(self):
        with _Tree() as t:
            shas = {n: t.write(n, '{"record_id": "%s"}' % n)
                    for n in ("a.json", "b.json", "c.md")}
            t.commit(shas)
            for n in shas:
                t.remove(n)
            buf = io.StringIO()
            rc = verify_with(buf)
            out = buf.getvalue()
            self.assertEqual(rc, 2, "must still refuse, not pass")
            self.assertIn("--verify-export", out)
            self.assertNotIn("cannot be withdrawn by deleting the file", out)

    def test_partial_absence_is_still_a_real_alarm(self):
        """The control. Without it the guard could swallow every absence."""
        with _Tree() as t:
            shas = {n: t.write(n, '{"record_id": "%s"}' % n)
                    for n in ("a.json", "b.json", "c.md")}
            t.commit(shas)
            t.remove("b.json")          # one gone, two present
            buf = io.StringIO()
            rc = verify_with(buf)
            out = buf.getvalue()
            self.assertEqual(rc, 2)
            self.assertIn("COMMITTED TO BUT NOT ON DISK", out)
            self.assertIn("b.json", out)
            self.assertNotIn("WRONG COMMAND", out)

    def test_an_intact_tree_still_passes(self):
        with _Tree() as t:
            shas = {n: t.write(n, '{"record_id": "%s"}' % n)
                    for n in ("a.json", "b.json")}
            t.commit(shas)
            buf = io.StringIO()
            self.assertEqual(verify_with(buf), 0, buf.getvalue())

    def test_an_altered_record_still_fails(self):
        """Altering must not be reachable through the new branch."""
        with _Tree() as t:
            shas = {n: t.write(n, '{"record_id": "%s"}' % n)
                    for n in ("a.json", "b.json")}
            t.commit(shas)
            t.write("a.json", '{"record_id": "a.json", "verdict": "edited"}')
            buf = io.StringIO()
            rc = verify_with(buf)
            self.assertEqual(rc, 2)
            self.assertIn("ALTERED", buf.getvalue())

    def test_an_empty_manifest_is_not_the_export_case(self):
        """Nothing committed to and nothing present is not a wrong command."""
        with _Tree() as t:
            t.commit({})
            buf = io.StringIO()
            rc = verify_with(buf)
            self.assertNotIn("WRONG COMMAND", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
