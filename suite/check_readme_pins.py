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
    # Whitespace-tolerant across the whole phrase, because hard line wrapping
    # can split it. On 22 Oct a rewording put "The" and "committed" on separate
    # lines; this check correctly exited 2 (CANNOT CHECK) rather than 0, which
    # is the designed behaviour and the reason that branch exists.
    m = re.search(
        r"committed\s+file\s+prints\s*`?\s*([0-9a-f]{64})", text)
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

    # --- pin 3: the suite case count --------------------------------------
    # README stated 359 in one place and 378 in another, 22 lines apart, while
    # the suite printed 395. Three figures for one counter, none current,
    # because nothing compared prose to output. Found 22 Oct by an audit.
    import subprocess
    # cwd is pinned deliberately. This shells out to the suite to read the case
    # count rather than trusting prose, which means the number this gate
    # publishes is whatever that subprocess prints. Without cwd=ROOT the result
    # would depend on where the checker happened to be invoked from, and a gate
    # whose verdict is a function of the caller's working directory is not a
    # gate. An agent reported seeing exactly that divergence on 22 Oct against a
    # mid-edit tree; it does NOT reproduce at HEAD, where both directories give
    # exit 0 and 401 cases. Pinned anyway, because the fragility is real even
    # when it is not currently biting.
    r = subprocess.run([sys.executable, str(ROOT / "suite" / "selftest.py")],
                       capture_output=True, text=True, cwd=str(ROOT))
    m = re.search(r"^(\d+) cases:", r.stdout, re.M)
    if not m:
        print("CANNOT CHECK: suite/selftest.py did not print '<n> cases:'.")
        return 2
    actual_cases = int(m.group(1))
    checked += 1
    claimed = [int(c) for c in re.findall(r"`suite/selftest\.py` \((\d+) cases", text)]
    claimed += [int(c) for c in re.findall(r"survived (\d+) suite cases", text)]
    if not claimed:
        print("CANNOT CHECK: no suite case count claimed in README.md.")
        return 2
    bad = [c for c in claimed if c != actual_cases]
    if bad:
        failures.append(
            f"suite/selftest.py prints {actual_cases} cases, but README.md "
            f"claims {sorted(set(bad))}. A case count in prose drifts every "
            "time a case is added; this is why it is checked.")
    else:
        print(f"ok   suite case count matches in {len(claimed)} README "
              f"claim(s)  ({actual_cases})")

    # --- pin 4: the selftest file count -----------------------------------
    n_selftests = len(list((ROOT / "suite").glob("selftest*.py"))) + \
                  len(list((ROOT / "gateway").glob("selftest*.py")))
    checked += 1
    words_rev = {v: k for k, v in words.items()}
    claimed_st = re.findall(
        r"(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
        r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
        r"twenty|\d+) self-test", text)
    extra = {"eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
             "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
             "nineteen": 19, "twenty": 20}
    lookup = dict(words_rev)
    lookup.update(extra)
    bad_st = []
    for c in claimed_st:
        val = lookup.get(c, int(c) if c.isdigit() else None)
        if val is not None and val != n_selftests:
            bad_st.append(c)
    if bad_st:
        failures.append(
            f"{n_selftests} selftest files exist, but README.md says "
            f"{sorted(set(bad_st))}.")
    elif claimed_st:
        print(f"ok   selftest file count matches in {len(claimed_st)} "
              f"README claim(s)  ({n_selftests})")

    # --- pin 5: no document may link into a repository we know is blocked --
    # README.md linked github.com/arian-gogani/nobulex in two places and
    # THESIS.md in one. That repository has returned HTTP 451 under a DMCA
    # takedown since 2026-10-20, so the first substantive sentence of the README
    # sent every reader to GitHub's takedown page, and did so for two days
    # including a day on which the README was edited.
    #
    # Checked statically rather than by HEAD-requesting every URL, so this stays
    # offline and deterministic like the rest of the suite. It cannot catch a
    # link that rots tomorrow; it does catch the one we already know is dead.
    BLOCKED_LINKS = ("github.com/arian-gogani/nobulex/",
                     "github.com/arian-gogani/nobulex)")
    for doc in ("README.md", "THESIS.md", "CONTRIBUTING.md"):
        dp = ROOT / doc
        if not dp.exists():
            print(f"CANNOT CHECK: {doc} is absent")
            return 2
        dt = dp.read_text()
        checked += 1
        hits = [b for b in BLOCKED_LINKS if b in dt]
        if hits:
            failures.append(
                f"{doc} links into arian-gogani/nobulex, which returns HTTP 451 "
                f"under a DMCA takedown. Matched: {hits}. State the direction in "
                "prose or point at a reachable destination.")
    if not any("links into arian-gogani/nobulex" in f for f in failures):
        print("ok   no document links into the DMCA-blocked repository")

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
