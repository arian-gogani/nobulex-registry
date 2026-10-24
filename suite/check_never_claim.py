#!/usr/bin/env python3
"""Refuse ten claims this project has no standing to make, on every public surface.

    python3 suite/check_never_claim.py

WHY THIS EXISTS, with the instances that caused it.

Four public corrections have been issued from this project, and all four were
the same defect: a claim stated at a wider scope than the evidence supported.
Not a fabricated number and not a lie about a run. A true sentence about one
artifact, published as a sentence about the category.

A prose list of such claims is the weaker half of a fix, because nobody runs
prose. The other half is this file. It is a sibling of
`suite/check_retracted_claims.py`, which gates claims that were published and
withdrawn; this one gates claims that must not be published in the first place,
whether or not they have been tried yet. Both exist because the project has
twice had a guard print PASS over the exact claim it was built to catch:

  * `check_retracted_claims.py` carried an entry scoped to README-only while
    the claim it named lived in THESIS.md, so the entry could never fire.
  * A web-claims check printed PASS while unable to catch a fabricated dollar
    recovery figure.

So two properties here are not optional. Every rule is matched by REGEX rather
than by a historical sentence, because a guard keyed to an exact sentence is
defeated by dropping one word from it. And every rule carries its own positive
and negative controls, asserted on each run: a rule that does not fire on its
own violation, or that fires on its own retraction, makes this script exit 2
rather than report clean. A guard that cannot fail is worse than no guard.

ASSERTION VERSUS DISCLOSURE. A document whose job is to retract a claim has to
be allowed to state it. `check_retracted_claims.py` solves that with per-surface
scoping: a phrase is checked only where its presence would be an assertion. All
four surfaces here are documents that disclose their own gaps, so scoping by
file would disable every rule. Instead the unit of judgement is the SENTENCE,
and a sentence carrying a negation or retraction cue ("Nothing routes production
traffic through it") is read as disclosure rather than assertion. Every such
excusal is counted and printed, so the exemptions are auditable rather than
silent. ALLOWLIST below carries the narrower cases, each with its reason.

Exits 0 when no unsupportable claim is asserted on any checked surface, 1 when
one is, and 2 when it cannot tell. A file it cannot read is a failure, not a
pass, and a rule that fails its own control is a failure, not a pass.

NOT wired into the pre-push hook. `brand/register.html` is a known, separately
tracked staleness (see `check_retracted_claims.py`, currently red for the same
reason), and a gate that blocks every push on a defect somebody else is already
tracking teaches people to pass --no-verify.

MEASURED PRECISION, AND WHY THIS IS NOT WIRED INTO THE PUSH HOOK.
-----------------------------------------------------------------
Run on 23 Oct 2026 against the repository it was written for, this reported
EIGHT findings. I judged each by hand. **Three were real and five were false
positives**, a 62 per cent false-positive rate:

  REAL   README "a record can be unalterable" (a sha256 makes an edit
         detectable, not impossible). Fixed the same day as a result of this
         script, which is the one thing it genuinely earned.
  REAL   brand/register.html twice, the known stale committed output that can
         only be regenerated in the tree holding the records.

  FALSE  "The current register displays the stored verdict" is describing what
         the artifact does, not claiming the product is current.
  FALSE  Two matches inside a RETRACTION paragraph that exists to say the quoted
         claim is the stale one.
  FALSE  THESIS narrating the generic recursion ("a registry gets built... and
         the registry publishes rows") as a failure mode, not as this registry.
  FALSE  A sentence that already states the correction, "It was closed unmerged
         on 11 September 2026", matched on the repo name alone.

The pattern is one thing: it cannot reliably tell an ASSERTION from a
DISCLOSURE, and the documents here are full of disclosures by design, because
retracting a claim in place is this project's whole method. Its own disclosure
heuristic caught six sentences and missed five.

A gate with a 62 per cent false-positive rate gets switched off, and then the
true positives stop being caught too. That is not a hypothetical: this
repository already pays for one noisy guard elsewhere. So `check_retracted_claims.py`
remains the gate, because its explicit phrases scoped per surface currently
report ZERO false positives, and this file stays as an ADVISORY sweep to run by
hand when adding a claim, with its measured rate stated above rather than left
for a reader to discover.

Kept rather than deleted because 74 patterns and 92 self-controls are real work
and the generalisation is the right long-term shape; it needs assertion-versus-
disclosure detection that works before it can gate anything.

"""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Every public surface in this repository that makes prose claims. brand/*.html
# is globbed rather than listed, because a new published page must be covered
# the day it is added rather than the day somebody remembers this file.
CHECKED_FILES = ["README.md", "THESIS.md", "CONTRIBUTING.md"]
CHECKED_GLOBS = ["brand/*.html"]


# ---------------------------------------------------------------------------
# Disclosure cues.
#
# A sentence carrying one of these is disclosing a gap, correcting a record, or
# speaking in the conditional, so the claim in it is not being asserted.
#
# "without" is deliberately ABSENT. It appeared in a first draft and it excused
# README's "a manifest that fixes each one by sha256 without disclosing a word
# of what it says, so a record can be unalterable", which is a live rule-5
# finding. A cue that excuses a claim because the sentence also denies something
# unrelated is how a guard goes quiet.
# ---------------------------------------------------------------------------
DISCLOSURE_CUES = re.compile(
    r"""(?xi)
    \b(?:no|not|never|nothing|nobody|none|neither|nor|zero|cannot|can't|
        isn't|aren't|wasn't|hasn't|haven't|doesn't|don't|didn't)\b
  | \b(?:would|could|intended|intends|specification|hypothetical|if)\b   # conditional
  | \bcorrection\b | \bpreviously\b | \bretract | \bwithdraw
  | \bwas\s+wrong\b | \boverclaim | \bunsupportable\b | \bmust\s+never\b
  | \bno\s+longer\b | \bstood\s+here\s+until\b | \bunmerged\b
  | \buntil\s+\d{1,2}\s+\w+\s+\d{4}\b      # "until 22 October 2026"
  | \bnot\s+yet\b | \bunearned\b | \bdrift
    """
)


# ---------------------------------------------------------------------------
# The ten rules. Each is (id, title, why_unsupportable, patterns, positive
# controls, negative controls).
#
# A pattern is (regex, why_this_shape) or (regex, why_this_shape, ABSOLUTE).
# Each carries a note saying why it is shaped the way it is, because the shape
# is the whole content of this file: the historical sentence is not what is
# being gated, the claim behind it is.
#
# ABSOLUTE means the disclosure cues do not excuse it. It is for claim forms
# that CONTAIN a negation, such as "cannot be altered": sentence-level negation
# scoping would otherwise make them unfirable, which is this project's own
# recorded failure mode. An absolute pattern can still be allowlisted by name.
# ---------------------------------------------------------------------------
ABSOLUTE = True
RULES = [
    {
        "id": "R1-ADOPTION",
        "title": "That anyone uses, has adopted, or has paid for Nobulex",
        "why": (
            "Zero customers, zero revenue, zero adoption, as of 23 Oct 2026. "
            "README's own 'Not yet true': \"No buyer has paid for a "
            "verification.\" THESIS: \"No relying party has paid.\""
        ),
        "patterns": [
            # The soft forms are the dangerous ones. "trusted by" and "used in
            # production" assert a user without naming one, so they cannot be
            # checked by a reader and cannot be defended by the author.
            (r"\btrusted\s+by\b", "soft adoption claim with no nameable subject"),
            (r"\b(?:used|running|deployed|live|in\s+use)\s+in\s+production\b",
             "asserts a production user"),
            (r"\bin\s+production\s+at\b", "asserts a named production user"),
            (r"\bbuilt\s+for\s+(?:teams|companies|finance\s+teams|operators|engineers)\b",
             "testimonial-shaped: implies the teams exist and arrived"),
            (r"\b(?:our|its)\s+(?:customers|clients|users|adopters|buyers)\b",
             "possessive form asserts the set is non-empty"),
            # Verb-first form, so dropping the possessive does not evade it.
            (r"\b(?:customers?|clients?|teams?|companies|users?|buyers?)\s+"
             r"(?:use|uses|rely\s+on|relies\s+on|trust|trusts|depend\s+on|"
             r"depends\s+on|have\s+adopted|has\s+adopted|adopted)\b",
             "asserts third parties in use"),
            (r"\b(?:adopted|in\s+use|deployed)\s+(?:by|at)\s+[A-Z]",
             "names an adopter"),
            (r"\badopted\s+(?:Nobulex|the\s+(?:suite|harness|gateway|registry))\b",
             "asserts adoption of the product"),
            (r"\b(?:paying|paid)\s+(?:customers?|pilots?|users?|buyers?|clients?)\b",
             "asserts revenue"),
            (r"\b(?:has|have|had)\s+paid\b",
             "asserts revenue; the negated form is disclosure and is excused"),
            (r"\b(?:first|our|annual|monthly|recurring|in)\s+revenue\s+"
             r"(?:of|is|was|reached)\b", "asserts a revenue figure"),
            # A star count on a claims surface is a use claim wearing a number.
            # "star the repository" and "Stars do not measure it" are not this.
            (r"\b\d[\d,]*\+?\s*(?:github\s+)?stars\b", "star count as proof of use"),
            (r"\bstars?\s+(?:prove|proves|show|shows|demonstrate|demonstrates)\b",
             "star count as proof of use"),
            (r"\btestimonial", "testimonial-shaped content"),
            (r"\bcase\s+stud(?:y|ies)\b", "a case study implies a customer"),
            (r"\bwhat\s+(?:our\s+)?(?:customers|users|teams)\s+say\b",
             "testimonial-shaped content"),
            (r"\bjoin\s+(?:\d|the\s+(?:hundreds|thousands|teams))\b",
             "crowd claim"),
            (r"\blogo\s+wall\b", "logo walls assert users; there are none"),
        ],
        "positive": [
            "Trusted by finance teams at four companies.",
            "Nobulex is used in production by two payment platforms.",
            # Written without a negation on purpose. The first draft of this
            # control was "Built for teams who cannot afford a silent billing
            # error", which the disclosure cues excused on the strength of a
            # "cannot" that was not denying the claim at all. That is a real
            # hole in sentence-level negation scoping and it is recorded in
            # NEVER-CLAIM-20261023.md rather than hidden behind a kinder
            # control.
            "Built for teams who bill by usage.",
            "Our customers run it over every invoice.",
            "Three paying customers renewed this quarter.",
            "Two buyers have paid for a verification.",
            "1,200 stars show the demand is real.",
            "Read the case study from our first pilot.",
        ],
        "negative": [
            "No buyer has paid for a verification.",
            "Nobody has stated what they would pay.",
            "Stars do not measure it.",
            "If you want to follow the work, star the repository.",
            "A worked example with no customer in it.",
            "They are customers of this role rather than competitors for it.",
        ],
    },
    {
        "id": "R2-REGISTRY-LIVE",
        "title": "That the registry is live or current",
        "why": (
            "The registry is a prior direction and its own page says so: "
            "\"This page is a prior direction, kept rather than deleted.\" The "
            "current direction is billing accuracy for usage-based products."
        ),
        "patterns": [
            # Shaped around the copula rather than the noun, because "the
            # registry" appears legitimately all over these files. Only a
            # sentence that puts it in the present as a live thing is a claim.
            (r"\b(?:registry|register)\s+is\s+(?:now\s+)?live\b",
             "asserts the prior direction is current"),
            (r"\bthe\s+(?:live|current)\s+(?:registry|register)\b",
             "same claim in adjective position"),
            (r"\b(?:registry|register)\s+is\s+(?:our|the)\s+current\b",
             "asserts the prior direction is the current one"),
            (r"\bcurrent\s+(?:product|direction|focus|offering)\s+is\s+the\s+"
             r"(?:registry|register)\b", "same claim reversed"),
            (r"\b(?:registry|register)\s+(?:is|remains)\s+(?:actively\s+)?"
             r"(?:maintained|supported|operational)\b",
             "asserts maintenance of a prior direction"),
            (r"\b(?:launch|launched|launching|shipping)\s+the\s+"
             r"(?:registry|register)\b", "asserts a launch that did not happen"),
            (r"\b(?:registry|register)\s+(?:now\s+)?publishes\b",
             "nothing is published; every record is held"),
        ],
        "positive": [
            "The Nobulex registry is live and accepting submissions.",
            "See the live register for current verdicts.",
            "The registry is the current product direction.",
            "The register is actively maintained.",
            "The register now publishes a verdict per subject.",
        ],
        "negative": [
            "The registry is a prior direction, kept rather than deleted.",
            "Nothing here is being maintained as a live product.",
            "Status is queried live against this register or it is not a status.",
            "It is resolved against this register, live, every time it is claimed.",
        ],
    },
    {
        "id": "R3-DOLLARS",
        "title": "That any specific dollar amount was recovered, saved or found",
        "why": (
            "No figure has ever been measured. There is no customer to measure "
            "one over, and `gateway/pilot.py` refuses to print even a catch "
            "rate over unlabelled data for exactly this reason."
        ),
        "patterns": [
            # Any currency figure at all on these four surfaces. Verified safe:
            # as of 23 Oct 2026 there is not one currency symbol in any of them,
            # so this fires on a new figure rather than on existing prose.
            (r"(?:\$|€|£)\s?\d", "any currency figure is unmeasured here"),
            (r"\b\d[\d,]*(?:\.\d+)?\s*(?:million|billion|trillion)\b",
             "a magnitude figure reads as money in this context"),
            # Verb-then-number and number-then-verb, so reordering does not
            # evade it. This is the pair a web-claims guard printed PASS over.
            (r"\b(?:recovered|saved|savings|recouped|clawed\s+back|recovery|"
             r"leakage)\b[^.]{0,30}?(?:\$|\b\d)",
             "attaches a number to a recovery claim"),
            (r"(?:\$\s?\d|\b\d[\d,]*)[^.]{0,30}?\b(?:recovered|saved|"
             r"in\s+savings|in\s+recoveries|of\s+leakage)\b",
             "same claim with the number first"),
            (r"\b(?:found|identified|surfaced|uncovered)\s+"
             r"(?:\$|\d[\d,]*\s*(?:million|billion|[kKmMbB])\b)",
             "attaches a measured magnitude to a finding"),
            (r"\b(?:ROI|return\s+on\s+investment)\s+of\b",
             "an ROI figure is a recovery figure"),
            (r"\bpays?\s+for\s+itself\b", "implied savings figure"),
        ],
        "positive": [
            "Nobulex recovered $4.2M in billing errors.",
            "It found 1.8 million in underbilled usage.",
            "Customers saved $90,000 in the first quarter.",
            "2.3 million recovered in the first pilot.",
            "An ROI of 7x in ninety days.",
            "It pays for itself in a month.",
        ],
        "negative": [
            "Nobulex publishes no dollar-denominated trust figure.",
            "It refuses to print a catch rate or a false-block rate.",
            "This constraint costs real money early.",
            "Anything at all in a currency is not warranted.",
        ],
    },
    {
        "id": "R4-INLINE",
        "title": "That the gateway is deployed inline anywhere",
        "why": (
            "README: \"The gateway is not inline anywhere. Nothing routes "
            "production traffic through it.\" Observe mode is a mode in the "
            "code, not a running deployment."
        ),
        "patterns": [
            # "is now an inline ... gateway" was the published form. Keyed to
            # the copula plus "inline" so an intervening word ("is now fully
            # inline") does not evade it, and so "is not inline" does not match.
            # The optional-modifier run is why this is a regex and not a
            # substring: the published sentence was "is now an inline
            # decision-integrity gateway", and "is now fully inline", "is
            # already inline" and "is an inline gateway" are the same claim.
            # "not" is deliberately not in the modifier set, so "is not inline"
            # does not match on its way past.
            (r"\b(?:is|are|runs|running|sits|sitting|operates|operating|"
             r"deployed)\s+(?:now\s+|fully\s+|already\s+|an?\s+|the\s+){0,3}"
             r"inline\b", "asserts inline operation"),
            (r"\b(?:an|the)\s+inline\s+(?:[\w-]+\s+){0,3}gateway\b",
             "asserts the product is inline, through up to three modifiers"),
            (r"\binline\s+(?:in|at|before)\s+(?:production|the\s+payment|"
             r"the\s+action|the\s+order)\b", "asserts an inline position"),
            (r"\broutes?\s+production\s+traffic\b",
             "asserts production traffic reaches it"),
            (r"\bbefore\s+the\s+action\s+executes\b",
             "only true of something inline; nothing is"),
            (r"\b(?:block|blocks|blocking|blocked)\s+(?:live|real|production)\s+"
             r"(?:orders?|traffic|payments?|data)\b",
             "asserts enforcement against real traffic"),
            (r"\bdeployed\s+(?:anywhere|in\s+production|at\s+a\s+customer)\b",
             "asserts a deployment"),
            (r"\bin\s+the\s+(?:critical|payment|order)\s+path\b",
             "asserts an inline position in other words"),
        ],
        "positive": [
            "Nobulex is now an inline decision-integrity gateway.",
            "The gateway is now fully inline at two operators.",
            "It permits, blocks or escalates before the action executes.",
            "It routes production traffic through a deterministic policy.",
            "The gateway sits inline in the payment path.",
            "It is blocking live orders today.",
            "The HTTP surface is deployed in production.",
        ],
        "negative": [
            "The gateway is not inline anywhere.",
            "Nothing routes production traffic through it, and nobody is "
            "blocking live orders or live data with it.",
            "No HTTP surface is deployed anywhere reachable but a developer's "
            "own machine.",
            "Observe mode is a mode in the code, not a running deployment.",
        ],
    },
    {
        "id": "R5-TAMPER",
        "title": "That anything is tamper-proof",
        "why": (
            "The receipts are tamper-EVIDENT. A hash chain detects an edit; it "
            "does not prevent one. THESIS: \"A hash chain makes a record "
            "tamper evident, but a false or incomplete record hash chains "
            "perfectly.\" Prevention is the one property it does not have."
        ),
        "patterns": [
            # The adjective, every spelling, because the published failure mode
            # here is a one-word substitution for "tamper-evident".
            (r"\btamper[\s-]?(?:proof|resistant|free)\b",
             "asserts prevention where only detection exists"),
            (r"\btamperproof\b", "same claim, closed up"),
            (r"\b(?:unalterable|immutable|unchangeable|unmodifiable)\b",
             "same claim without the word 'tamper'; a hash commitment makes an "
             "edit detectable, not impossible"),
            # ABSOLUTE: the claim form contains its own "cannot", so sentence
            # negation scoping would make it unfirable. The lookahead keeps the
            # one honest version of the sentence ("cannot be altered without
            # detection") out of the findings.
            (r"\bcannot\s+be\s+(?:altered|edited|changed|modified|tampered|"
             r"forged|faked)\b(?!\s+(?:without|undetect|unnotic))",
             "asserts prevention", ABSOLUTE),
            (r"\b(?:prevents?|prevented|preventing)\s+(?:tampering|alteration|"
             r"edits|modification|forgery)\b", "asserts prevention"),
            (r"\b(?:hash[\s-]?chain|receipts?|signature)s?\s+"
             r"(?:prevent|prevents|stop|stops|make[s]?\s+it\s+impossible)\b",
             "attributes prevention to a detection mechanism"),
        ],
        "positive": [
            "The receipts are tamper-proof.",
            "Hash-chained and tamperproof end to end.",
            "A committed record is unalterable.",
            "The chain is immutable once written.",
            "A signed receipt cannot be altered.",
            "The hash chain prevents tampering.",
        ],
        "negative": [
            "A hash chain makes a record tamper evident, but a false record "
            "hash chains perfectly.",
            "A hash chain makes a false record tamper-evident rather than true.",
            "Receipts hold hashes, not payloads.",
        ],
    },
    {
        "id": "R6-REGULATION",
        "title": "That anything satisfies a regulation",
        "why": (
            "No EU AI Act, SOC, ISO or compliance claim is supportable. No "
            "procurement function has accepted an attestation and none has "
            "been issued. THESIS describes the Act's shape; describing a "
            "regulation is not satisfying one."
        ),
        "patterns": [
            # Verb-keyed, because THESIS discusses the EU AI Act, notified
            # bodies and conformity assessment legitimately and at length. The
            # claim is in the verb, never in the name of the regulation.
            (r"\b(?:compliant\s+with|compliance\s+with|complies\s+with|"
             r"conforms\s+to|conformant\s+with|satisfies|meets|fulfils|"
             r"fulfills)\s+(?:the\s+)?(?:EU\s+AI\s+Act|AI\s+Act|SOC|ISO|GDPR|"
             r"HIPAA|PCI|NIS2|DORA|SOX)\b", "asserts regulatory satisfaction"),
            (r"\b(?:SOC\s?2|ISO\s?\d{4,5}|ISO/IEC\s?\d+|GDPR|HIPAA|PCI[\s-]?DSS|"
             r"SOX)[\s-]?(?:compliant|certified|ready|attested|aligned)\b",
             "badge form of the same claim"),
            (r"\b(?:audit|compliance|procurement|regulator)[\s-]ready\b",
             "unearned readiness claim"),
            (r"\b(?:satisfies|meets|discharges|fulfils|fulfills)\s+"
             r"(?:a\s+|any\s+|the\s+|your\s+)?(?:regulatory|statutory|"
             r"compliance|audit)\s+(?:requirement|obligation|duty|burden)\b",
             "asserts regulatory satisfaction without naming the regulation"),
            (r"\bNobulex\s+(?:is|has\s+been)\s+(?:certified|accredited|"
             r"approved|compliant|audited)\b", "asserts an accreditation"),
            (r"\bnotified\s+body\s+(?:has|accepted|approved|recognis|recogniz)",
             "asserts recognition by a conformity body"),
        ],
        "positive": [
            "Nobulex receipts are SOC 2 compliant.",
            "ISO 27001 certified evidence.",
            "A procurement-ready attestation.",
            "It satisfies the EU AI Act logging obligation.",
            "This meets your audit requirement.",
            "Nobulex is accredited for conformity assessment.",
        ],
        "negative": [
            "The EU AI Act's Annex III high risk obligations now land on 2 "
            "December 2027, and most of those systems use internal self "
            "assessment.",
            "The Act largely codifies self certification.",
            "Third party conformity assessment by a notified body is required "
            "only for biometric categorisation.",
        ],
    },
    {
        "id": "R7-MERGE-IS-NOT-ADOPTION",
        "title": "That a merge means adoption",
        "why": (
            "A maintainer merging a fix to his own code has accepted a fix, "
            "not adopted a product. This distinction has already been got "
            "wrong once, in writing."
        ),
        "patterns": [
            # The general form of this is an inference, not a string, so these
            # patterns catch the stated version only: a merge put next to an
            # adoption or usage word in the same sentence.
            (r"\b(?:merged|merges|merge|accepted|landed)\b[^.]{0,80}?"
             r"\b(?:adopt|adopted|adoption|adopter)\b",
             "puts a merge and an adoption in one sentence"),
            (r"\b(?:adopt|adopted|adoption|adopter)\b[^.]{0,80}?"
             r"\b(?:merged|merges|merge|accepted|landed)\b",
             "same pairing, reversed"),
            (r"\b(?:merged|accepted)\s+(?:PRs?|pull\s+requests?|patches?|"
             r"fixes)\b[^.]{0,60}?\b(?:prove|proves|show|shows|mean|means|"
             r"demonstrate|demonstrates|evidence\s+of)\b",
             "treats merge count as evidence of something else"),
            (r"\b(?:maintainers?|projects?|repos?|repositories)\s+(?:now\s+)?"
             r"(?:use|uses|rely\s+on|relies\s+on|run|runs)\s+"
             r"(?:Nobulex|the\s+(?:suite|harness|gateway))\b",
             "asserts third-party use from a merge"),
            (r"\b(?:is|are)\s+(?:now\s+)?(?:a\s+)?(?:Nobulex\s+)?"
             r"(?:user|users|adopter|adopters|customer|customers)\s+"
             r"(?:after|because|since)\b[^.]{0,40}?\bmerg",
             "derives a user from a merge explicitly"),
        ],
        "positive": [
            "Four merged PRs, so the project has adopted Nobulex.",
            "Adoption at MeterGraph followed the merge of three fixes.",
            "Merged pull requests prove the method is being used.",
            "Two maintainers now use the harness.",
            "They are a Nobulex user since the merge of the window fix.",
        ],
        "negative": [
            "A maintainer merging a fix to his own code has accepted a fix, "
            "not adopted a product.",
            "A merge is not adoption and must never be written as one.",
            "Three pull requests were merged in twenty-five hours.",
        ],
    },
    {
        "id": "R8-YFINANCE-2967",
        "title": 'That a closed-unmerged PR was an "upstream fix"',
        "why": (
            "ranaroussi/yfinance#2967 was closed unmerged on 11 Sep 2026, by "
            "the author. Nothing upstream was fixed. The phrase stood in "
            "THESIS.md until 22 Oct 2026 and was wrong the whole time."
        ),
        "patterns": [
            (r"\bupstream\s+(?:fix|fixes|patch|patches|contribution)\b",
             "the exact published phrase; negated and corrected forms are "
             "excused by the disclosure cues"),
            (r"\b(?:fixed|landed|merged|accepted)\s+upstream\b",
             "same claim with the words swapped, which is how a guard keyed to "
             "the phrase alone gets evaded"),
            (r"\b(?:yfinance|ranaroussi/yfinance)\s*#?\s*2967\b[^.]{0,80}?"
             r"\b(?:merged|fixed|fix|landed|accepted|shipped)\b",
             "names the instance and claims an outcome it did not have"),
            (r"\b(?:merged|fixed|landed|accepted|shipped)\b[^.]{0,80}?"
             r"\b(?:yfinance|ranaroussi/yfinance)\s*#?\s*2967\b",
             "same pairing, reversed"),
            (r"\bupstream\s+now\s+(?:carries|has|includes|returns)\b",
             "asserts the change is in upstream code"),
        ],
        "positive": [
            "One upstream fix arising from this line of work.",
            "The adjustment change was merged upstream.",
            "ranaroussi/yfinance#2967 was accepted on 11 September.",
            "We landed yfinance#2967.",
            "Upstream now carries the observable adjustment.",
        ],
        "negative": [
            "It was closed unmerged on 11 September 2026, so nothing upstream "
            'was fixed and the phrase "upstream fix" was wrong.',
            "One public pull request arising from this line of work, against "
            "ranaroussi/yfinance, proposed making a suppressed adjustment "
            "observable; it was not merged.",
        ],
    },
    {
        "id": "R9-PRODUCTION-CI",
        "title": "That production CI depends on his repository",
        "why": (
            "Overstated once and withdrawn. The workflow carrying that "
            "allowlist entry is `workflow_dispatch` only: 21 manual runs, last "
            "on 13 Sep, and the entry was added on 14 Sep, so the workflow has "
            "never executed with it. A dependency that has never run is not a "
            "dependency."
        ),
        "patterns": [
            (r"\bproduction\s+CI\b",
             "the phrase itself; the only CI involved is workflow_dispatch and "
             "has never run with the entry"),
            (r"\b(?:CI|pipelines?|workflows?|builds?)\s+(?:now\s+)?"
             r"(?:depends?|depend|relies|rely|hinges)\s+on\b",
             "asserts a dependency"),
            (r"\b(?:depends?\s+on|relies\s+on|depended\s+on|relied\s+on)\s+"
             r"(?:this|his|our|the\s+Nobulex)\s+(?:repo|repository|package|"
             r"action)\b", "same claim pointed at the repository"),
            (r"\b(?:allowlist|allow-list|allowlisted)\b[^.]{0,80}?"
             r"\b(?:production|CI|pipeline|gate|enforced)\b",
             "the allowlist entry presented as a live gate"),
            (r"\b(?:used|consumed|pinned|required)\s+by\s+"
             r"[A-Za-z0-9/_.-]+(?:'s)?\s+(?:CI|pipeline|workflow|build)\b",
             "asserts a named consumer's CI uses it"),
            (r"\bruns?\s+in\s+(?:their|its|production|upstream)\s+"
             r"(?:CI|pipeline|workflow)\b", "asserts execution in their CI"),
            (r"\bgates?\s+(?:their|its|upstream)\s+(?:merges?|releases?|"
             r"builds?|CI)\b", "asserts an enforcing gate"),
        ],
        "positive": [
            "Production CI depends on this repository.",
            "Their pipeline now depends on the Nobulex action.",
            "The allowlist entry is enforced in CI on every push.",
            "It is pinned by MeterGraph's CI.",
            "It runs in their CI on every pull request.",
            "It gates their releases.",
        ],
        "negative": [
            "A green CI badge does not measure it.",
            "The workflow is workflow_dispatch only and has never executed "
            "with that entry, so no CI depends on it.",
        ],
    },
    {
        "id": "R10-NOPCOMMERCE-8405",
        "title": "That nopCommerce#8405 is accepted, confirmed or fixed",
        "why": (
            "It was triaged, milestoned and assigned within twelve hours, and "
            "nobody has commented on it. Triage is a maintainer sorting an "
            "inbox, not a maintainer agreeing. Claim the triage and nothing "
            "more."
        ),
        "patterns": [
            (r"\bnopCommerce\s*#?\s*8405\b[^.]{0,80}?"
             r"\b(?:accepted|confirmed|fixed|merged|resolved|validated|"
             r"acknowledged|agreed)\b",
             "names the instance and claims an outcome beyond triage"),
            (r"\b(?:accepted|confirmed|fixed|merged|resolved|validated|"
             r"acknowledged)\b[^.]{0,80}?\bnopCommerce\b",
             "same pairing, reversed, so word order does not evade it"),
            (r"[#]\s?8405\b[^.]{0,60}?\b(?:accepted|confirmed|fixed|merged|"  # noqa
             # [#] not #. Every pattern here is compiled with re.X,
             # under which a bare # STARTS A COMMENT, so this pattern
             # became empty and matched every line in every file: 729
             # false findings out of 737. A character class is immune.
             r"resolved|validated)\b", "the bare issue number with an outcome"),
            # Triage misread as agreement, named or not. This is the general
            # shape of the error, and it is worth catching without the number.
            (r"\b(?:triaged|milestoned|assigned)\b[^.]{0,60}?"
             r"\b(?:accepted|confirmed|validated|agreed|acknowledged)\b",
             "reads triage as agreement"),
            (r"\b(?:accepted|confirmed|validated|agreed|acknowledged)\b"
             r"[^.]{0,60}?\b(?:triaged|milestoned|assigned)\b",
             "same, reversed"),
        ],
        "positive": [
            "nopCommerce#8405 was confirmed by the maintainers.",
            "The fix was accepted in nopCommerce.",
            "#8405 was validated within twelve hours.",
            "It was triaged and therefore accepted.",
            "Acknowledged, since it was milestoned and assigned.",
        ],
        "negative": [
            "It was triaged, milestoned and assigned within twelve hours, and "
            "nobody has commented, so it is not accepted or confirmed.",
            "Claim the triage and nothing more.",
        ],
    },
]


# ---------------------------------------------------------------------------
# Allowlist for legitimate quotation, each entry with its reason.
#
# An entry suppresses one rule on one file when the given substring is present
# in the same sentence. It is deliberately narrow: a rule-wide or file-wide
# exemption is how a gate stops being one. Nothing here may be added to make a
# red run green without a reason that survives being read aloud.
# ---------------------------------------------------------------------------
ALLOWLIST = [
    # (relative path, rule id, substring that must be in the sentence, reason)
    (
        "README.md",
        "R2-REGISTRY-LIVE",
        "resolved against the register, live, or it does not resolve",
        "This is the anti-badge rule: it says a status must be queried live "
        "rather than copied into a PNG. It is a constraint on badges, not a "
        "claim that the register is a live product.",
    ),
    (
        "brand/register.template.html",
        "R2-REGISTRY-LIVE",
        "resolved against this register, live, every time it is claimed",
        "Same anti-badge rule in the published page's own words.",
    ),
    (
        "brand/register.html",
        "R2-REGISTRY-LIVE",
        "resolved against this register, live, every time it is claimed",
        "Same anti-badge rule in the stale committed copy.",
    ),
]


# ---------------------------------------------------------------------------
# Text extraction. Line numbers must survive it, because a finding without a
# line is a finding somebody has to go hunting for.
# ---------------------------------------------------------------------------
def _blank_preserving_newlines(match: re.Match) -> str:
    """Replace a span with the same number of newlines it contained."""
    return "\n" * match.group(0).count("\n")


def strip_markup(text: str, is_html: bool) -> str:
    if not is_html:
        return text
    # Comments first: a retracted claim parked in a comment is still committed,
    # but a comment EXPLAINING a claim must not be read as asserting it. These
    # pages carry both, and the explanatory kind is the common one, so comments
    # are removed rather than scanned.
    text = re.sub(r"<!--.*?-->", _blank_preserving_newlines, text, flags=re.S)
    text = re.sub(r"<(script|style)\b.*?</\1>", _blank_preserving_newlines,
                  text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return html.unescape(text)


_BOUNDARY = re.compile(r"^\s*(?:#{1,6}\s|[-*+]\s|\d+\.\s|\||>|```)")
_SENTENCE_END = re.compile(r"(?<=[.!?:])\s+")


def units(text: str) -> list[tuple[int, str]]:
    """Split into (line_number, sentence) pairs.

    The unit is the sentence, because assertion and disclosure are decided at
    sentence scope: README asserts nothing when it writes "Nothing routes
    production traffic through it", and the next sentence over is a different
    claim. Paragraph and list boundaries also cut, so a heading with no full
    stop does not drag its negation into the paragraph below it.
    """
    out: list[tuple[int, str]] = []
    buf: list[str] = []
    buf_start = 1

    def flush() -> None:
        if not buf:
            return
        para = "\n".join(buf)
        pos = 0
        for piece in _SENTENCE_END.split(para):
            if not piece.strip():
                pos += len(piece) + 1
                continue
            at = para.find(piece, pos)
            if at < 0:
                at = pos
            line = buf_start + para.count("\n", 0, at)
            out.append((line, re.sub(r"\s+", " ", piece).strip()))
            pos = at + len(piece)
        buf.clear()

    for idx, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or _BOUNDARY.match(line):
            flush()
            buf_start = idx
        if not buf:
            buf_start = idx
        buf.append(line)
    flush()
    return out


def allowlisted(rel: str, rule_id: str, sentence: str) -> str | None:
    for path, rid, needle, reason in ALLOWLIST:
        if path == rel and rid == rule_id and needle.lower() in sentence.lower():
            return reason
    return None


def unpack(pattern: tuple) -> tuple[str, str, bool]:
    """(regex, shape) or (regex, shape, ABSOLUTE)."""
    return (pattern[0], pattern[1], len(pattern) > 2 and bool(pattern[2]))


def scan_text(rel: str, text: str, is_html: bool):
    findings = []
    excused_disclosure = 0
    excused_allowlist = 0
    for line, sentence in units(strip_markup(text, is_html)):
        for rule in RULES:
            for raw in rule["patterns"]:
                pattern, shape, absolute = unpack(raw)
                m = re.search(pattern, sentence, re.I | re.X)
                if not m:
                    continue
                if not absolute and DISCLOSURE_CUES.search(sentence):
                    excused_disclosure += 1
                    break
                reason = allowlisted(rel, rule["id"], sentence)
                if reason:
                    excused_allowlist += 1
                    break
                findings.append({
                    "file": rel, "line": line, "rule": rule,
                    "quote": m.group(0), "sentence": sentence, "shape": shape,
                })
                break
    return findings, excused_disclosure, excused_allowlist


# ---------------------------------------------------------------------------
# Controls. A rule that cannot fire is the defect this file was written about,
# so the rules are tested on every run rather than trusted.
# ---------------------------------------------------------------------------
def run_controls() -> list[str]:
    failures = []
    for rule in RULES:
        unpacked = [unpack(p) for p in rule["patterns"]]
        for sentence in rule["positive"]:
            fired = [(p, a) for p, _s, a in unpacked
                     if re.search(p, sentence, re.I | re.X)]
            if not fired:
                failures.append(
                    f"{rule['id']}: positive control did not fire: {sentence!r}")
            elif DISCLOSURE_CUES.search(sentence) and not any(
                    a for _p, a in fired):
                failures.append(
                    f"{rule['id']}: positive control is excused as disclosure, "
                    f"so the rule cannot fire on it: {sentence!r}")
        for sentence in rule["negative"]:
            hit = any(re.search(p, sentence, re.I | re.X) and
                      (a or not DISCLOSURE_CUES.search(sentence))
                      for p, _s, a in unpacked)
            if hit:
                failures.append(
                    f"{rule['id']}: negative control fires and is not excused, "
                    f"which is a false positive: {sentence!r}")
    return failures


def main() -> int:
    control_failures = run_controls()
    if control_failures:
        print("CANNOT CHECK: this script's own rules failed their controls. A "
              "rule that does not fire on its own violation reports clean for "
              "the wrong reason.\n")
        for line in control_failures:
            print(f"  {line}")
        return 2

    targets = [Path(p) for p in CHECKED_FILES]
    for glob in CHECKED_GLOBS:
        matched = sorted(ROOT.glob(glob))
        if not matched:
            print(f"CANNOT CHECK: {glob} matched no files. A surface that "
                  "cannot be found must not read as clean.")
            return 2
        targets += [p.relative_to(ROOT) for p in matched]

    findings = []
    excused_disclosure = 0
    excused_allowlist = 0
    checked = 0

    for rel in targets:
        path = ROOT / rel
        if not path.exists():
            print(f"CANNOT CHECK: {rel} is absent. A surface that cannot be "
                  "read must not read as clean.")
            return 2
        try:
            text = path.read_text()
        except OSError as exc:
            print(f"CANNOT CHECK: {rel} could not be read: {exc}")
            return 2
        checked += 1
        f, d, a = scan_text(str(rel), text, path.suffix.lower() == ".html")
        findings += f
        excused_disclosure += d
        excused_allowlist += a

    if not checked:
        print("CANNOT CHECK: no surfaces were examined, which is not a pass.")
        return 2

    pattern_count = sum(len(r["patterns"]) for r in RULES)
    control_count = sum(len(r["positive"]) + len(r["negative"]) for r in RULES)
    print(f"{checked} surface(s) examined against {len(RULES)} rules / "
          f"{pattern_count} patterns. {control_count} controls passed, so every "
          f"rule fired on its own violation and none fired on its own "
          f"retraction.")
    print(f"{excused_disclosure} sentence(s) matched a pattern and were read as "
          f"disclosure rather than assertion (negation, correction or "
          f"conditional in the same sentence).")
    print(f"{excused_allowlist} sentence(s) matched and were allowlisted by "
          f"name, with a stated reason.")
    print()

    if findings:
        print(f"{len(findings)} unsupportable claim(s) asserted:\n")
        for f in findings:
            print(f"  {f['file']}:{f['line']}  [{f['rule']['id']}]")
            print(f"    matched:   {f['quote']!r}")
            print(f"    in:        {f['sentence'][:200]}")
            print(f"    pattern:   {f['shape']}")
            print(f"    why wrong: {f['rule']['why']}")
            print()
        print("Each of these is a claim stated at a wider scope than the "
              "evidence supports, which is the shape of all four public "
              "corrections this project has issued. Narrow the sentence, or "
              "delete it. If a sentence is genuinely a quotation or a "
              "retraction, add it to ALLOWLIST with its reason rather than "
              "widening a pattern.")
        return 1

    print("No unsupportable claim is asserted on any checked surface.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
