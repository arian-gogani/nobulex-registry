#!/usr/bin/env python3
"""Refuse to let a retracted claim survive in any copy of a published page.

    python3 suite/check_retracted_claims.py

WHY THIS EXISTS, with the instance that caused it.

On 22 October 2026 the register template was corrected to remove two claims:
that Nobulex "is now an inline decision-integrity gateway... before the action
executes", and that Nobulex "proves what happened on the other side". Both are
retracted in README.md's own words: "The gateway is not inline anywhere.
Nothing routes production traffic through it", and "Nothing is published."

The template was fixed. The live site was redeployed with the fix. But
`brand/register.html`, the committed output, was never regenerated, so the ONLY
copy still carrying both retracted claims was the one in version control. Three
copies of one page, and the one under source control was the wrong one.

It could not simply be regenerated either: `render_register.py` correctly
refuses in a public checkout, because compiling a held count from records it
cannot read would publish "0 held" over a manifest committing to four. That
refusal is right, and it means this particular staleness can only be fixed in
the tree that holds the records. Which is exactly why it needs a gate here
rather than a good intention there.

A retracted claim is worse than a wrong number. A number drifts; a retracted
claim was examined, found false, and published anyway.

Exits 0 when no retracted claim appears in any checked copy, 1 when one does,
and 2 when it cannot tell. A file it cannot read is a failure, not a pass.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Claims that were examined, found false, and retracted. Each carries the
# retraction's own source so a reader can check the judgement rather than take
# it. Add to this list; never remove an entry because a copy still has it.
# A document whose job is to retract a claim has to be allowed to QUOTE it. On
# first run this script flagged README.md for containing "before the action
# executes", which appears there only inside a paragraph retracting it. A gate
# that cannot tell an assertion from a retraction produces false positives, and
# a gate with false positives gets switched off, after which it catches nothing.
#
# So each phrase is scoped to the surfaces where its presence would be an
# assertion. Published pages and the generators that write records assert; the
# README documents, including documenting what was withdrawn.
PUBLISHED = ("brand/register.html", "brand/register.template.html",
             "suite/run.py", "suite/hold.py")
DOCS = ("README.md",)

RETRACTED = [
    (PUBLISHED, "is now an inline decision-integrity gateway",
     'README.md: "The gateway is not inline anywhere. Nothing routes '
     'production traffic through it."'),
    (PUBLISHED, "before the action executes",
     'Same retraction: nothing is deployed inline, so nothing happens '
     '"before the action executes".'),
    (PUBLISHED, "proves what happened on the other side",
     'README.md: "Nothing is published." And a signature proves who signed, '
     "not that the claim was true."),
    (DOCS, "## What is sold",
     'README.md\'s own "Not yet true" section: "No buyer has paid for a '
     'verification." A heading in the present tense over an empty order book.'),
    (DOCS, "procurement-ready attestation",
     "Unearned: no procurement function has accepted one, and none has been "
     "issued."),
    (DOCS, "re-runs the pinned suite against the pinned subject on a schedule",
     "No scheduler exists in this repository. Verified by searching for cron, "
     "schedule, celery, systemd and launchd across every Python file."),
    (PUBLISHED, "Queried outside this window the record returns EXPIRED",
     'README.md: "Automatic expiry at lookup is intended behavior, not '
     'implemented enforcement in this register."'),
]

# Every copy of a published surface that lives in this repository.
CHECKED = [
    Path("brand/register.html"),
    Path("brand/register.template.html"),
    # The GENERATORS too, not only their output. The EXPIRED claim was
    # retracted in README.md and kept being written into every new record by
    # these two files, so checking only the rendered page would have missed
    # the source that reintroduces it on the next run.
    Path("suite/run.py"),
    Path("suite/hold.py"),
    # README itself, for present-tense claims over things that do not exist.
    Path("README.md"),
]


def main() -> int:
    findings = []
    checked = 0

    for rel in CHECKED:
        path = ROOT / rel
        if not path.exists():
            print(f"CANNOT CHECK: {rel} is absent. A copy that cannot be read "
                  "must not read as clean.")
            return 2
        try:
            text = path.read_text()
        except OSError as exc:
            print(f"CANNOT CHECK: {rel} could not be read: {exc}")
            return 2
        checked += 1
        for scope, phrase, retraction in RETRACTED:
            if str(rel) not in scope:
                continue
            if phrase in text:
                findings.append((rel, phrase, retraction))

    if not checked:
        print("CANNOT CHECK: no copies were examined, which is not a pass.")
        return 2

    print(f"{checked} surface(s) examined against {len(RETRACTED)} retracted "
          f"claim(s), each scoped to the surfaces where it would be an "
          f"assertion rather than a quotation.")
    print()

    if findings:
        print(f"{len(findings)} retracted claim(s) still present:\n")
        for rel, phrase, retraction in findings:
            print(f"  {rel}")
            print(f"    still contains: {phrase!r}")
            print(f"    retracted by:   {retraction}")
            print()
        print("If the template is already corrected and only the committed "
              "output is stale, it has to be regenerated in the tree that "
              "holds the records:")
        print("    python3 suite/render_register.py "
              "--publish /path/to/nobulex-web/register.html")
        print("render_register.py refuses in a public checkout, and that "
              "refusal is correct rather than a bug.")
        return 1

    print("No retracted claim appears in any checked copy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
