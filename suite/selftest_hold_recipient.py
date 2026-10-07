"""Offline regression of the publication gate's recipient requirement.

No record on disk, no subject process, no network. The gate function is
exercised directly against constructed records.

The case that matters is the one where every other obligation is met: the
artifact is recorded as delivered, the window is recorded as long closed, and
the only thing missing is the name of the party it was owed to. Before this
check existed the gate opened on that record, because it verified that a
delivery had been written down without verifying that anyone had been named to
receive it.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import runpy
import unittest


SOURCE = Path(__file__).with_name("hold.py")
NAMESPACE = runpy.run_path(str(SOURCE), run_name="hold_recipient_regression")
blocked = NAMESPACE["_reply_obligation_unmet"]

LONG_CLOSED = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
DELIVERED = (datetime.now(timezone.utc) - timedelta(days=37)).isoformat()


def record(**ror):
    """A record satisfying every reply obligation except those overridden."""
    base = {"required": True,
            "recipient": "maintainer of subject repository "
                         "https://github.com/example/subject.git",
            "artifact_delivered_at": DELIVERED,
            "window_closes_at": LONG_CLOSED}
    base.update(ror)
    return {"publication": {"right_of_reply": base}}


class RecipientGateTests(unittest.TestCase):
    def test_otherwise_complete_record_clears(self):
        """The control. Without this passing, the cases below prove nothing."""
        self.assertIsNone(blocked(record()))

    def test_unnamed_recipient_blocks_an_otherwise_complete_record(self):
        for recipient in (None, "", "   ", 123, [], {}):
            with self.subTest(recipient=recipient):
                why = blocked(record(recipient=recipient))
                self.assertIsNotNone(
                    why, "a record naming no recipient must not clear")
                self.assertIn("no recipient is named", why)

    def test_missing_recipient_key_entirely_blocks(self):
        rec = record()
        del rec["publication"]["right_of_reply"]["recipient"]
        self.assertIn("no recipient is named", blocked(rec) or "")

    def test_recipient_is_asked_before_delivery(self):
        """Both missing: the report names the unanswerable question first.

        Telling an operator to deliver an artifact before telling them there is
        nobody to deliver it to sends them to do the impossible thing first.
        """
        why = blocked(record(recipient=None, artifact_delivered_at=None))
        self.assertIn("no recipient is named", why)

    def test_check_does_not_fire_when_no_reply_is_required(self):
        """A publishable record has no right_of_reply block to inspect."""
        self.assertIsNone(blocked({"publication": {"right_of_reply": None}}))
        self.assertIsNone(blocked({"publication": {}}))
        self.assertIsNone(blocked(
            {"publication": {"right_of_reply": {"required": False}}}))

    def test_named_recipient_still_requires_delivery(self):
        """The new check must not short-circuit the obligations after it."""
        why = blocked(record(artifact_delivered_at=None))
        self.assertIn("never delivered", why)
        why = blocked(record(window_closes_at=None))
        self.assertIn("window_closes_at is unset", why)


if __name__ == "__main__":
    unittest.main()
