"""The publication gate must refuse a record whose bytes moved during the window.

Offline. A temporary tree, no network, no git, nothing in the real records
directory touched.

WHY THIS FILE EXISTS. hold.py's module docstring promised that anyone could
hash a published record and compare it to the digest committed on the day it
was issued, and that matching proved the verdict was untouched while the
subject was answering. That comparison was impossible: clearing rewrites
publication.status, cleared_at, cleared_from and all three validity fields
before the file moves, so the published bytes differ from the committed digest
every time, tampered or not. Measured on an untampered record: committed
56087c0c..., published a4b9481d.... Matching could not occur, non-matching
carried no information, and no code anywhere performed the comparison.

The guarantee now lives where it can be kept: the record is hashed against its
commitment BEFORE anything is stamped, a mismatch refuses, and the verified
digest is carried into the published file as publication.held_digest so a
reader can still check it against the committed manifest.
"""
import datetime
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
HOLD = runpy.run_path(str(HERE / "hold.py"), run_name="hold_clear_integrity")
clear, sha256 = HOLD["cmd_clear"], HOLD["sha256"]
G = clear.__globals__

# Delivery and the window's close are DIFFERENT instants, seven days apart.
# They were the same value, which is a zero-length window: the subject was
# told they had seven days and the record said the window shut the moment the
# artifact went out. The old gate accepted it because it only asked whether
# the deadline had passed, never how long the window was.
_NOW = datetime.datetime.now(datetime.timezone.utc)
DELIVERED = (_NOW - datetime.timedelta(days=30)).isoformat()
CLOSES = (_NOW - datetime.timedelta(days=23)).isoformat()
PAST = DELIVERED


class _Tree:
    def __enter__(self):
        self.root = tempfile.mkdtemp(prefix="nblx-clearint-")
        self.held = os.path.join(self.root, "records", "held")
        os.makedirs(self.held)
        self.saved = {k: G[k] for k in ("ROOT", "RECORDS", "HELD", "MANIFEST")}
        G["ROOT"] = self.root
        G["RECORDS"] = os.path.join(self.root, "records")
        G["HELD"] = self.held
        G["MANIFEST"] = os.path.join(self.root, "records",
                                     "held.manifest.json")
        return self

    def __exit__(self, *exc):
        G.update(self.saved)
        shutil.rmtree(self.root, ignore_errors=True)
        return False

    def record(self, rid, **over):
        rec = {"record_id": rid, "verdict": "FAIL_UNSAFE",
               "subject": {"package": "example"},
               "publication": {
                   "status": "HELD", "held_by": "right_of_reply",
                   "right_of_reply": {
                       "required": True,
                       "recipient": "maintainer of subject repository "
                                    "https://github.com/example/s.git",
                       "window_days": 7,
                       "artifact_delivered_at": DELIVERED,
                       "window_closes_at": CLOSES,
                       "reply_received_at": None}}}
        rec.update(over)
        p = os.path.join(self.held, rid + ".json")
        with io.open(p, "w", encoding="utf-8") as fh:
            json.dump(rec, fh, indent=2, ensure_ascii=False)
        return p

    def commit(self, *paths):
        with io.open(G["MANIFEST"], "w", encoding="utf-8") as fh:
            json.dump({"held": [{"file": os.path.basename(p),
                                 "sha256": sha256(p),
                                 "bytes": os.path.getsize(p)}
                                for p in paths]}, fh, indent=2)

    def edit(self, path, **over):
        with io.open(path, encoding="utf-8") as fh:
            rec = json.load(fh)
        rec.update(over)
        with io.open(path, "w", encoding="utf-8") as fh:
            json.dump(rec, fh, indent=2, ensure_ascii=False)

    def published(self, rid):
        return os.path.join(G["RECORDS"], rid + ".json")


def _quiet(fn, *a):
    err, out = sys.stderr, sys.stdout
    sys.stderr = sys.stdout = io.StringIO()
    try:
        return fn(*a)
    finally:
        sys.stderr, sys.stdout = err, out


class ClearChecksTheCommitment(unittest.TestCase):

    def test_an_untouched_record_clears(self):
        """The control. Without it the refusals below could be a gate that
        refuses everything."""
        with _Tree() as t:
            p = t.record("NBLX-19990101-201")
            t.commit(p)
            self.assertEqual(_quiet(clear, "NBLX-19990101-201"), 0)
            self.assertTrue(os.path.exists(t.published("NBLX-19990101-201")))

    def test_the_published_record_carries_the_digest_it_held(self):
        with _Tree() as t:
            p = t.record("NBLX-19990101-202")
            before = sha256(p)
            t.commit(p)
            _quiet(clear, "NBLX-19990101-202")
            with io.open(t.published("NBLX-19990101-202"),
                         encoding="utf-8") as fh:
                out = json.load(fh)
            self.assertEqual(out["publication"]["held_digest"],
                             "sha256:" + before)

    def test_a_verdict_flipped_during_the_window_is_refused(self):
        """The attack the headline promise claimed to catch and never did."""
        with _Tree() as t:
            p = t.record("NBLX-19990101-203")
            t.commit(p)
            t.edit(p, verdict="PASS")
            self.assertEqual(_quiet(clear, "NBLX-19990101-203"), 2)
            self.assertFalse(os.path.exists(t.published("NBLX-19990101-203")))

    def test_any_byte_change_is_refused_not_just_the_verdict(self):
        with _Tree() as t:
            p = t.record("NBLX-19990101-204")
            t.commit(p)
            t.edit(p, subject={"package": "something-else"})
            self.assertEqual(_quiet(clear, "NBLX-19990101-204"), 2)

    def test_an_unreadable_manifest_refuses_rather_than_skips(self):
        """An unread manifest is not a clean one, which is the whole doctrine."""
        with _Tree() as t:
            t.record("NBLX-19990101-205")
            with io.open(G["MANIFEST"], "w", encoding="utf-8") as fh:
                fh.write("{ not json")
            self.assertEqual(_quiet(clear, "NBLX-19990101-205"), 2)

    def test_a_record_not_in_the_manifest_still_clears(self):
        """Deliberate: a record nothing committed to has no commitment to
        violate. The HELD-but-uncommitted case is cmd_verify's to refuse, and
        conflating them here would block the first record ever issued."""
        with _Tree() as t:
            t.record("NBLX-19990101-206")
            t.commit()
            self.assertEqual(_quiet(clear, "NBLX-19990101-206"), 0)


class WithdrawnIsNotRepublished(unittest.TestCase):

    def test_trailing_newline_still_counts_as_withdrawn(self):
        # render_register.is_withdrawn documents this exact shape as already
        # found and fixed there; hold.py kept the unstripped copy seven lines
        # below one that strips.
        with _Tree() as t:
            p = t.record("NBLX-19990101-207", status="WITHDRAWN\n")
            t.commit(p)
            self.assertEqual(_quiet(clear, "NBLX-19990101-207"), 1)
            self.assertFalse(os.path.exists(t.published("NBLX-19990101-207")))

    def test_surrounding_whitespace_and_case(self):
        for spelling in ("  WITHDRAWN  ", "withdrawn", "Withdrawn\t"):
            with self.subTest(status=spelling):
                with _Tree() as t:
                    p = t.record("NBLX-19990101-208", status=spelling)
                    t.commit(p)
                    self.assertEqual(_quiet(clear, "NBLX-19990101-208"), 1)

    def test_a_non_string_status_does_not_crash_the_gate(self):
        with _Tree() as t:
            p = t.record("NBLX-19990101-209", status={"v": "WITHDRAWN"})
            t.commit(p)
            self.assertIn(_quiet(clear, "NBLX-19990101-209"), (0, 1, 2))

    def test_control_a_record_with_no_status_key_still_clears(self):
        with _Tree() as t:
            p = t.record("NBLX-19990101-210")
            t.commit(p)
            self.assertEqual(_quiet(clear, "NBLX-19990101-210"), 0)


class TheGateDoesNotTakeAuthorityFromTheRecord(unittest.TestCase):
    """held_by is committed to the manifest and printed on the register as the
    gate. The command that opens the gate did not read it, so deleting one key
    inside the record removed every precondition."""

    blocked = staticmethod(HOLD["_reply_obligation_unmet"])

    def _ror(self, **over):
        now = datetime.datetime.now(datetime.timezone.utc)
        d = now - datetime.timedelta(days=30)
        ror = {"required": True, "window_days": 7,
               "recipient": "maintainer of subject repository "
                            "https://github.com/example/s.git",
               "artifact_delivered_at": d.isoformat(),
               "window_closes_at": (d + datetime.timedelta(days=7)).isoformat(),
               "reply_received_at": None}
        ror.update(over)
        return {"publication": {"status": "HELD",
                                "held_by": "right_of_reply",
                                "right_of_reply": ror}}

    def test_control_a_discharged_obligation_clears(self):
        self.assertIsNone(self.blocked(self._ror()))

    def test_a_deleted_reply_block_is_refused_not_waved_through(self):
        rec = {"publication": {"status": "HELD",
                               "held_by": "right_of_reply",
                               "right_of_reply": None}}
        self.assertIn("held_by", self.blocked(rec) or "")

    def test_required_false_against_a_reply_gate_is_a_contradiction(self):
        self.assertIsNotNone(self.blocked(self._ror(required=False)))

    def test_a_record_not_held_under_reply_is_unaffected(self):
        """The control for the cross-check: a publishable record has no block
        and must not start being refused."""
        rec = {"publication": {"status": "PUBLISHABLE", "held_by": None,
                               "right_of_reply": None}}
        self.assertIsNone(self.blocked(rec))


class TheWindowIsTheWindowThatWasPromised(unittest.TestCase):
    """The only temporal check was now < deadline, with the deadline read from
    the record being cleared. window_days, which run.py writes as 7, was never
    read by anything."""

    blocked = staticmethod(HOLD["_reply_obligation_unmet"])

    def _at(self, closes=None, **over):
        now = datetime.datetime.now(datetime.timezone.utc)
        d = now - datetime.timedelta(days=30)
        ror = {"required": True, "window_days": 7,
               "recipient": "maintainer of subject repository "
                            "https://github.com/example/s.git",
               "artifact_delivered_at": d.isoformat(),
               "window_closes_at": (closes or d + datetime.timedelta(days=7)
                                    ).isoformat(),
               "reply_received_at": None}
        ror.update(over)
        return ({"publication": {"status": "HELD",
                                 "held_by": "right_of_reply",
                                 "right_of_reply": ror}}, d, now)

    def test_a_one_second_window_is_refused(self):
        rec, d, _ = self._at()
        rec["publication"]["right_of_reply"]["window_closes_at"] = \
            (d + datetime.timedelta(seconds=1)).isoformat()
        self.assertIn("shorter than", self.blocked(rec) or "")

    def test_a_window_closing_before_delivery_is_refused(self):
        rec, d, _ = self._at()
        rec["publication"]["right_of_reply"]["window_closes_at"] = \
            (d - datetime.timedelta(days=1)).isoformat()
        self.assertIsNotNone(self.blocked(rec))

    def test_a_truthy_non_timestamp_reply_does_not_close_the_window(self):
        rec, _d, now = self._at(closes=now_plus(5))
        rec["publication"]["right_of_reply"]["reply_received_at"] = "pending"
        self.assertIn("not a readable timestamp", self.blocked(rec) or "")

    def test_a_reply_predating_delivery_is_not_a_reply(self):
        rec, d, _ = self._at(closes=now_plus(5))
        rec["publication"]["right_of_reply"]["reply_received_at"] = \
            (d - datetime.timedelta(days=2)).isoformat()
        self.assertIn("precedes delivery", self.blocked(rec) or "")

    def test_control_a_genuine_reply_closes_an_open_window(self):
        rec, _d, now = self._at(closes=now_plus(5))
        rec["publication"]["right_of_reply"]["reply_received_at"] = \
            (now - datetime.timedelta(days=1)).isoformat()
        self.assertIsNone(self.blocked(rec))

    def test_a_nonsense_window_days_is_refused(self):
        for bad in (0, -3, True, "seven", None):
            with self.subTest(window_days=bad):
                rec, _d, _ = self._at()
                rec["publication"]["right_of_reply"]["window_days"] = bad
                self.assertIsNotNone(self.blocked(rec))


def now_plus(days):
    return (datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(days=days))


if __name__ == "__main__":
    unittest.main()
