"""The shortest spelling of a held id walked past all three disclosure scans.

Offline. No git, no records directory.

A record id is NBLX-yyyymmdd-nnn, and the three scans compared the whole
string. Prose drops the prefix as soon as the record has been mentioned once:
"and 00000000-901 is refused" is simply how a sentence about a second record
comes out. The tail identifies the record exactly as well as the full id, so a
commit message naming a held record and stating what the gate did with it was
not a leak according to any of them.

Found by writing one. The scan caught the prefixed id in a tracked file and in
the message beside it, refused the push, printed three paragraphs about it, and
said nothing at all about the bare tail sitting in the very next commit's
message. A guard that catches the careful spelling and misses the natural one
catches the author who was already being careful.

The comparison lives in ids_in, which all three scans call, because that
function's own docstring records what happened when they each had their own
copy: three scans comparing the same wrong way are one scan.
"""
from pathlib import Path
import runpy
import unittest

HERE = Path(__file__).resolve().parent
HOLD = runpy.run_path(str(HERE / "hold.py"), run_name="hold_id_tail")
ids_in = HOLD["ids_in"]
canon_ids = HOLD["canon_ids"]
_id_tail = HOLD["_id_tail"]

HELD = ["NBLX-00000000-901"]
C = canon_ids(HELD)


class TheTailIsTheLeak(unittest.TestCase):

    def test_the_bare_date_and_sequence_is_found(self):
        self.assertEqual(ids_in("and 00000000-901 is refused", C), HELD)

    def test_the_sentence_that_prompted_this(self):
        self.assertEqual(
            ids_in("002 and 003 would clear, and 00000000-901 is refused "
                   "for its subject name.", C),
            HELD)

    def test_the_full_id_is_still_found(self):
        """The tail is a substring of every spelling, so this must not
        regress when the comparison narrows to it."""
        self.assertEqual(ids_in("holds NBLX-00000000-901 today", C), HELD)

    def test_lower_case_is_still_found(self):
        self.assertEqual(ids_in("nblx-00000000-901", C), HELD)

    def test_the_spelling_that_was_found_is_never_returned(self):
        """The caller's job is to not disclose a held record, so the scan
        reports which id leaked in the manifest's spelling and never the
        substring it matched."""
        self.assertEqual(ids_in("00000000-901", C), HELD)


class ItStaysQuietOnCleanText(unittest.TestCase):
    """A confident false alarm in a push guard is worse than none: the reader
    cannot tell it from the real thing and discounts the next one."""

    def test_an_unrelated_record_is_not_reported(self):
        self.assertEqual(ids_in("NBLX-00000000-902", C), [])

    def test_an_unrelated_tail_is_not_reported(self):
        self.assertEqual(ids_in("00000000-902", C), [])

    def test_a_longer_sequence_number_is_a_different_record(self):
        self.assertEqual(ids_in("00000000-9012", C), [])

    def test_a_digit_on_the_left_is_a_different_record_too(self):
        """Both sides need bounding and only the right one was, which no test
        noticed: dropping the left check passed the whole file. A sequence can
        be swallowed from either end."""
        self.assertEqual(ids_in("100000000-901", C), [])

    def test_a_tail_bounded_by_punctuation_still_counts(self):
        """The control for the two above. Bounding must reject longer numbers
        without rejecting the ordinary way an id appears in a sentence."""
        for text in ("(00000000-901)", "00000000-901.", "see 00000000-901, ok",
                     "00000000-901"):
            with self.subTest(text=text):
                self.assertEqual(ids_in(text, C), HELD)

    def test_ordinary_prose_is_not_reported(self):
        for text in ("fix the renderer", "see commit 8ed9998",
                     "bumped to 2.3.1", "window closes in 7 days", ""):
            with self.subTest(text=text):
                self.assertEqual(ids_in(text, C), [])

    def test_no_held_ids_means_nothing_matches(self):
        self.assertEqual(ids_in("NBLX-00000000-901", canon_ids([])), [])

    def test_a_non_string_is_not_searched(self):
        self.assertEqual(ids_in(None, C), [])
        self.assertEqual(ids_in(7, C), [])


class AnUnrecognisedShapeNarrowsRatherThanWidens(unittest.TestCase):

    def test_a_shapeless_id_falls_back_to_itself(self):
        """Not to a substring that could appear anywhere. Widening here would
        turn the push guard into one that refuses on unrelated text."""
        self.assertEqual(_id_tail("not-an-id"), "not-an-id")

    def test_an_empty_id_stays_empty(self):
        self.assertEqual(_id_tail(""), "")
        self.assertEqual(_id_tail(None), None)

    def test_an_empty_tail_matches_nothing(self):
        """canon_ids drops ids that canonicalise to empty, so this guard is
        not reachable from the CLI today and removing it passed every other
        test here. It stays, and is tested directly, because "" is in every
        string: without it one unusable id in the manifest turns the push
        guard into one that refuses every push and names a record for it.
        """
        present = HOLD["_tail_present"]
        self.assertFalse(present("", "any text at all"))
        self.assertFalse(present(None, "any text at all"))

    def test_a_shapeless_id_does_not_match_everything(self):
        shapeless = canon_ids(["weird-record"])
        self.assertEqual(ids_in("some unrelated commit message", shapeless),
                         [])
        self.assertEqual(ids_in("holds weird-record", shapeless),
                         ["weird-record"])


if __name__ == "__main__":
    unittest.main()
