"""The subject name that existed only on the machine that ran the harness.

Offline. Nothing is read from or written to the records directory.

A run installs its subject from a working copy, so subject.package can end up
holding the directory the repository was checked out into instead of the name
the software is distributed under. Every verdict-bearing field can be sound and
the origin and commit can identify the subject exactly, and the record still
satisfies every other clear-time check, because not one of them looks at the
name.

The name is what publishes. The register renders subject.package, so an adverse
finding reaches readers under a string that exists nowhere but the machine that
ran the harness, and two runs of one piece of software arrive on the page under
different names with nothing to tell a reader they are one subject. The notice
that goes to a maintainer resolves the distribution name correctly, which makes
this the shape this suite keeps finding: two copies of one fact, one of them
right, and the wrong copy is the one that gets published.

The guard is not a style rule. The distribution name is in the record: a local
file:// requirement whose path ends in the declared package name, carrying a
different distribution name, is the signature of a field holding a path tail.
That is decidable, so the refusal names the replacement rather than asking.
"""
from pathlib import Path
import runpy
import unittest

HERE = Path(__file__).resolve().parent
HOLD = runpy.run_path(str(HERE / "hold.py"), run_name="hold_subject_name")
misnamed = HOLD["_subject_misnamed"]


def _rec(package, deps):
    return {"subject": {"package": package,
                        "execution_environment":
                            {"resolved_dependencies": deps}}}


class TheDirectoryNameIsRefused(unittest.TestCase):

    def test_a_checkout_directory_standing_in_for_the_package(self):
        msg = misnamed(_rec("subj", [
            "yfinance==1.7.0",
            "acme-quotes-mcp @ file:///tmp/run/subj"]))
        self.assertIsNotNone(msg)

    def test_the_refusal_names_the_distribution_to_use(self):
        """A refusal that does not say what to write instead is a wall."""
        msg = misnamed(_rec("subj", ["acme-quotes-mcp @ file:///tmp/run/subj"]))
        self.assertIn("acme-quotes-mcp", msg)

    def test_a_trailing_slash_on_the_location_still_matches(self):
        self.assertIsNotNone(misnamed(_rec("subj", [
            "acme-quotes-mcp @ file:///tmp/run/subj/"])))

    def test_a_generic_checkout_name_is_caught_too(self):
        """'subj' is one project's habit. The guard is about the shape."""
        for d in ("src", "pkg", "checkout", "work"):
            with self.subTest(dir=d):
                self.assertIsNotNone(misnamed(_rec(d, [
                    "acme-quotes-mcp @ file:///tmp/run/" + d])))


class RealRecordsStillClear(unittest.TestCase):
    """Without these the guard above could be one that refuses everything."""

    def test_a_record_naming_its_package_correctly(self):
        self.assertIsNone(misnamed(_rec("acme-quotes-mcp", [
            "acme-quotes-mcp @ file:///tmp/run/subj"])))

    def test_a_package_installed_from_a_directory_of_its_own_name(self):
        """The ordinary case: cloned into a directory named for the package.

        Here the path tail and the package agree, so there is nothing to
        correct, and an earlier draft that fired on any file:// requirement
        refused this.
        """
        self.assertIsNone(misnamed(_rec("acme-quotes-mcp", [
            "acme-quotes-mcp @ file:///tmp/acme-quotes-mcp"])))

    def test_a_record_with_no_local_requirements(self):
        self.assertIsNone(misnamed(_rec("acme-quotes-mcp",
                                        ["yfinance==1.7.0", "numpy==2.5.3"])))

    def test_an_unrelated_local_requirement_does_not_implicate_the_subject(self):
        self.assertIsNone(misnamed(_rec("acme-quotes-mcp", [
            "some-helper @ file:///tmp/build/some-helper"])))


class MalformedRecordsAreNotTheGuardsBusiness(unittest.TestCase):
    """It is a naming check. A missing field is some other check's refusal,
    and raising here would turn an unrelated defect into this one."""

    def test_no_subject_block(self):
        self.assertIsNone(misnamed({}))

    def test_no_execution_environment(self):
        self.assertIsNone(misnamed({"subject": {"package": "x"}}))

    def test_no_package(self):
        self.assertIsNone(misnamed(
            {"subject": {"execution_environment":
                         {"resolved_dependencies": ["a @ file:///t/a"]}}}))

    def test_a_non_string_package(self):
        self.assertIsNone(misnamed(_rec(None, ["a @ file:///t/a"])))
        self.assertIsNone(misnamed(_rec({"name": "subj"},
                                        ["a @ file:///t/a"])))

    def test_a_non_string_requirement(self):
        self.assertIsNone(misnamed(_rec("subj", [None, 7, {"a": "b"}])))

    def test_dependencies_absent_entirely(self):
        self.assertIsNone(misnamed(
            {"subject": {"package": "subj", "execution_environment": {}}}))


if __name__ == "__main__":
    unittest.main()
