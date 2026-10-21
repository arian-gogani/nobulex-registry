#!/usr/bin/env python3
"""Check that numbers README.md pins actually match the files it pins them to.

    python3 suite/check_readme_pins.py

WHY THIS EXISTS. README.md publishes a sha256 of `brand/register.html` and
tells a reader to compute it themselves, calling that "the one claim on this
project that a stranger can settle right now, without taking anyone's word for
anything." It also promises "The hash will change whenever the register
legitimately changes."

On 20 October 2026 an audit found it had not. A fourth record was held, the
generator rebuilt the page, and the pinned value went stale while the sentence
beneath it still read "The value above is the current one." Three record counts
elsewhere in the same file were stale for the same reason.

Nothing compared the pinned value to the file, so nothing failed. A published
number that no code checks is a number that drifts, and this project's whole
argument is that evidence must state what it establishes. So the check is here
rather than in a reader's hands.

Exits 0 when every pin matches, 1 when any has drifted, 2 when it cannot tell.
A pin it cannot locate is a failure, not a pass: a renamed heading must not
silently turn this into a no-op.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    readme = ROOT / "README.md"
    page = ROOT / "brand" / "register.html"

    for f in (readme, page):
        if not f.exists():
            print(f"CANNOT CHECK: {f.relative_to(ROOT)} is absent")
            return 2

    text = readme.read_text()
    failures = []
    checked = 0

    # --- pin 1: the committed register's sha256 -----------------------------
    m = re.search(
        r"the committed file prints\s*\n?`([0-9a-f]{64})`", text)
    if not m:
        print("CANNOT CHECK: no 'the committed file prints `<sha256>`' pin found "
              "in README.md. If that sentence was reworded, reword this check "
              "with it; a pin that cannot be located must not read as a pass.")
        return 2
    pinned = m.group(1)
    actual = hashlib.sha256(page.read_bytes()).hexdigest()
    checked += 1
    if pinned != actual:
        failures.append(
            "README.md pins the committed register as\n"
            f"    {pinned}\n"
            "but brand/register.html hashes to\n"
            f"    {actual}\n"
            "The register changed and the pinned value was not updated. Rebuild "
            "or repin, and do not leave 'The value above is the current one' "
            "standing over a stale number.")
    else:
        print(f"ok   committed register sha256 matches README  ({actual[:16]}...)")

    # --- pin 2: the held-record count, README vs the page it describes ------
    # The page is generated from the records, so it is the authority here. The
    # README is prose and drifts; this is exactly how it drifted.
    page_text = page.read_text()
    pm = re.search(r"(\d+)\s+records issued and withheld", page_text)
    if not pm:
        print("CANNOT CHECK: brand/register.html does not state "
              "'<n> records issued and withheld'.")
        return 2
    page_count = int(pm.group(1))
    checked += 1

    words = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
             6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}
    expected_word = words.get(page_count, str(page_count))

    # Every README phrase that states a held-record count.
    count_claims = re.findall(
        r"(?:manifest committing to|a page stating that|For the)\s+"
        r"(one|two|three|four|five|six|seven|eight|nine|ten|\d+)"
        r"\s+records?", text)
    if not count_claims:
        print("CANNOT CHECK: no held-record count claim found in README.md.")
        return 2
    # Make coverage visible rather than assumed. This checker matches a
    # hand-written list of phrasings, so it can only ever report "these claims
    # are right", never "the README is right". Any other "<n> records" phrase is
    # listed as UNCLASSIFIED so a reader sees what was not checked, which is the
    # discipline this repository applies to its own verdicts.
    all_phrases = re.findall(
        r"\b(one|two|three|four|five|six|seven|eight|nine|ten)\s+records?\b", text)
    unclassified = len(all_phrases) - len(count_claims)
    if unclassified > 0:
        print(f"note {unclassified} other '<n> records' phrase(s) in README.md are "
              f"NOT checked here (phrasings this script does not match). Found "
              f"{sorted(set(all_phrases))}; classified {len(count_claims)}. "
              "Some legitimately refer to other quantities, e.g. records "
              "published rather than held. This line exists so that is visible "
              "instead of reading as full coverage.")

    wrong = [c for c in count_claims if c != expected_word]
    if wrong:
        failures.append(
            f"brand/register.html states {page_count} records issued and withheld, "
            f"so README.md should read '{expected_word}', but it states: "
            f"{', '.join(sorted(set(wrong)))}.\n"
            "A count drifting downward reads as findings having been quietly "
            "dropped, which README.md itself says is the reason to publish it.")
    else:
        print(f"ok   held-record count matches the page in "
              f"{len(count_claims)} README claim(s)  ({expected_word})")

    print()
    if failures:
        print(f"{len(failures)} pin(s) have drifted:\n")
        for f in failures:
            print(f + "\n")
        return 1

    print(f"{checked} pinned claim(s) checked, all match.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
