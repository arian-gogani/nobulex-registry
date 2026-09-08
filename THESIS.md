# Why this role has to exist

Nobulex independently verifies what machines actually do, so others can decide what they should be allowed to do.

The README of this repository describes the mechanism: what a record is, what the five verdicts mean, what a subject tuple contains, who pays, and what the project has not yet done. This document is the argument underneath it. It is here because a project claiming that evidence must state what it establishes should state what its own reasoning rests on, and should say what would prove it wrong.

## Authenticity is not accuracy

Organisations need evidence that machine systems behave as claimed. Almost every mechanism now being standardised for that purpose runs on evidence created by the party being evaluated.

An agent records its own actions. An operator signs those records. A receipt proves the same key produced them. A hash chain proves the records were not later changed. A disclosure describes the operator's independence, its controls, or its evidence sources.

Each of those establishes authenticity and internal consistency, and each is worth having. None of them establishes that the original account was true or complete. A signature proves who made a claim. It does not prove the claim was accurate. A hash chain makes a record tamper evident, but a false or incomplete record hash chains perfectly. If the operator chooses what to record, it can omit an action, misstate an outcome, or sign an inaccurate account at the moment the event occurs, and every downstream cryptographic property still holds.

A party can make claims about itself. It cannot independently attest to itself. That is not a limitation of the cryptography, and no better primitive removes it.

## The recursion

The reason this is a structural argument rather than a product comparison is that every attempt to fix self attestation reproduces self attestation one level up.

Signed receipts fix tampering, so a registry gets built to collect them, and the registry publishes rows that are the described party's claim next to that party's own link. Unverifiable independence gets fixed by requiring independence to be stated, which is a statement by the party about itself. Someone notices the statement can go stale and adds a validity period, which makes it self reported and fresh. And the scope of such a statement can be wrong from the day it is written while every clause in it reads true.

That last one is not hypothetical here. A disclosure regime was run over this project's own repositories, and its scope was wrong four separate times. A gate covered a rendered preview but not the records behind it. A banner covering code, spec and packages did not reach an adopters file that discloses. None of those was stale. Each was true, current, and scoped to the wrong artifacts from the beginning. A validity period does not catch that. Enumerating what is in scope, and checking the gate against the enumeration, does.

The regress does not terminate in a better primitive. It terminates in one place only: a party that goes and looks.

## The missing role

What the stack lacks is a party outside the system being evaluated that executes the declared capability and records what actually came back.

Nobulex occupies that role. It does not countersign the operator's account. It runs the check, observes the result, compares it against ground truth fixed before execution, and publishes the supporting evidence.

This does not replace signed receipts, audit logs, transparency services or attestation protocols. Those preserve and transport evidence, and they do it well. Nobulex determines what that evidence independently establishes, and what it does not.

The category is not this project's invention, which is a point in its favour rather than against it. The security considerations of draft-kuehlewind-audit-architecture-01 state that the architecture does not solve the case of an adversarial service that refuses to record what happened at its boundary. As of September 2026 the proposed AUDIT working group charter is being amended, by its own authors, to say that audit information must be verifiable by a party that trusts neither the agent nor its operator, and that this property is what separates audit records from most existing logging. Independent parties in a standards venue are writing down the seat. Nobody has to take our word that it is empty.

## What a verdict has to satisfy

Five properties. Four are about the test. The fifth is about the sentence describing it, and it is the one the field keeps getting wrong.

**Falsifiability.** A check may be described as tested only when at least one defined input makes it report adversely. A check that always passes, that verifies only the successful artifact, or that cannot recognise the failure it claims to detect is not verification. It manufactures the appearance of assurance, which is worse than no check at all, because it displaces the scrutiny that would otherwise have happened. This is why suite/selftest.py exists and why it is the first thing this repository asks a stranger to attack.

**Independent execution.** The subject cannot control the test, select the observed result, or decide what outcome is recorded. Execution happens from outside the operator's control domain, and the exact artifact is resolved by the verifier rather than accepted from the subject's description of itself.

**Reproducibility.** Each verdict ships artifacts sufficient for another qualified party to repeat the procedure and evaluate the result. The verifier does not have to be believed on the strength of claimed expertise or claimed independence.

Reproducibility has a real constraint worth stating rather than hiding. Authoritative reference data is frequently licensed and frequently non redistributable, so for many subjects the values used cannot be republished. The resolution is that reproducibility is satisfied by publishing everything needed to repeat the comparison rather than everything needed to skip it: the named authority, the retrieval time, the exact query, the tolerance, and a cryptographic commitment to the retrieved values. A party with its own entitlement to the same authority can reproduce the verdict. A party without one can verify that we committed to the values before we saw the result. Where a suite can be built on primary sources that are public, it is, precisely because that makes the verdict checkable by more people.

**Publication completeness.** Runs are committed before their results are known, and an append only register shows that a record exists even while it is held for right of reply. This is what prevents a verifier from testing repeatedly and publishing only the favourable outcomes. Withholding a subject's identity during its response window can be justified. Hiding the existence of the held record cannot.

**Scope enumeration.** A verdict states what it does not establish over an enumerated set, and the enumeration is published with it. Stating the negative is necessary and not sufficient, because the statement ranges over a set and the set can be wrong on day one. This property exists because of the four scope failures described above, and it is the property this project has broken most often in its own work.

## Grading the verifier

Independent verification raises the obvious question. Why should anyone trust Nobulex?

They should not have to.

Verifier independence is graded on a public, mechanically recomputable scale, W0 through W4, with an explicit undetermined state for the case where available evidence cannot establish independence at all. The scale measures structural facts: control domain separation, key custody, how the tested artifact was resolved, and whether the evaluated party can influence execution or publication. The scale, its conformance vectors and a reference implementation are public at github.com/arian-gogani/witness-independence. Nobulex publishes its own grade under the same methodology.

The undetermined state is load bearing rather than decorative. Silence about a relationship is not evidence of independence, and a scale without a place to put "not established" will round silence upward. That is the specific failure mode of every reputation score, and this project has already produced one: an earlier version computed a number in which each refusal raised standing, so an agent refused fifty times outranked one refused twice, and the test suite asserted that behaviour was correct. A grade must be able to go down, and it must be able to say nothing.

The grade does not prove a verdict is true. It establishes the verifier's relationship to the subject. Falsifiability, reproducibility, completeness and scope enumeration supply the rest.

## The two attacks that would break this

A verifier that has not named its own attack surface is asking to be trusted.

**The indeterminate sink.** Precommitting runs stops a verifier from suppressing an unfavourable pass or fail. It does nothing about an unbounded indeterminate, which would let any awkward result be filed as undecidable. So an indeterminate requires a reason drawn from a closed, published list, the indeterminate rate is published per suite and per subject, and a rate that moves when a subject becomes commercially significant is itself a visible fact. An escape hatch that is counted in public is not an escape hatch.

**Detection and special casing.** Executing from outside the operator's control domain does not stop the operator from recognising the verifier and behaving differently for it. This is the defeat device problem, and it is the canonical attack on every independent testing regime that has ever existed. The mitigations are operational rather than cryptographic: probes that are not attributable, access acquired through ordinary commercial channels rather than a disclosed testing relationship, randomised timing and request identity, and periodic re execution under a fresh identity to compare against the attributed result. A divergence between attributed and unattributed runs is not a nuisance. It is the most serious finding this system can produce, and it is reportable as such.

Neither mitigation is complete. Both are stated, because a limit that has been named can be priced by the party relying on it.

## What this may not become

These are constraints rather than preferences, and each one has a corpse behind it.

The rated party cannot buy its verdict. Issuer pays destroyed the credit rating agencies, and it would destroy this faster, because this project has no regulatory moat to survive on afterwards. Revenue comes from relying parties. The one bounded exception, a maintainer funded re test of a subject already in the register, is described in the README and carries three mandatory conditions on the record itself.

No consulting or remediation for a rated party. That separation exists in financial auditing because the combination proved unmanageable, not because it was unpleasant.

No equity and no revenue share in a rated party.

No permanent badge. A static image on someone else's site outlives the conditions that justified it, keeps rendering green after a verdict is withdrawn, and cannot be revoked. Verification resolves against the register, live, or it does not resolve.

Methodology limits are published before disputes rather than during them. A limitation first articulated in response to a specific complaint is not a limitation. It is a defence.

## Why the adjacent seats are not this one

Receipt and audit log formats preserve and transport evidence. None of them executes anything, and a format cannot occupy a role.

Self issued receipt platforms are the closest and the most instructive. The best of them is genuinely good work, including standalone conformance corpora that import none of their own code and checkers that catch shape preserving semantic tampering. They still sign the issuer's account of what happened, and their results surfaces publish rows submitted by the parties those rows describe. That is not a defect in their engineering. It is the position they occupy.

Reputation and gateway scoring ranks servers on access and behaviour signals. It does not ask whether the server returned the right answer.

Accountable operators, meaning vendors selling outcomes with guarantees attached, do not self certify. They carry external insurers and independent assessors, because standing behind an outcome still requires someone else in the loop. They are customers of this role rather than competitors for it.

Regulators are not going to fill it either. The EU AI Act's Annex III high risk obligations now land on 2 December 2027, and most of those systems use internal self assessment. Third party conformity assessment by a notified body is required only for biometric categorisation and for AI used as a safety component in critical infrastructure. The Act largely codifies self certification. It creates demand for evidence and does not supply the party.

## The moat, ordered by what exists

Independence is not a moat. Any genuinely separate organisation can claim it.

What compounds is measurement infrastructure and accumulated institutional trust, and the items differ enormously in how soon they are real.

Startable now, requiring nobody's permission: open conformance and reproduction tools, and precommitted adversarial suites. Historically this is the item that decides this kind of market, and it is the reason the suite in this repository is MIT licensed and the reason a stranger is invited to break it.

Accruing with use: the longitudinal dataset of machine failures, historical behaviour across versions and environments, and a public record of having published unfavourable findings.

Slowest and decisive: integration into enterprise decision points, and recognition by auditors, insurers, procurement functions and standards bodies.

The ordering matters more than the list. A plan in which each stage depends on the last is a common way this kind of company dies, so stage one has to be worth something on its own even if nothing after it happens. Open tools are worth something on their own.

## What would make this wrong

A document arguing that claims must state what would disprove them has to do it itself. Each of the following is observable rather than a matter of opinion.

Relying parties do not pay for evidence they did not generate. If enterprises and platforms prefer a vendor's own attestation at a lower price, the missing role is missing because nobody wants it. This is the live risk and the one nothing in this document answers.

The failure class turns out to be rare. The whole model rests on tools returning plausible wrong answers at a rate that matters. If a broad, adversarial, honestly published suite finds overwhelmingly passes and loud failures, the category is real and too small.

Operators special case the verifier faster than probes can be made unattributable. If attributed and unattributed runs diverge routinely and the divergence cannot be closed, verdicts measure our own traffic rather than the tool.

Platforms internalise it. If the large agent platforms run adversarial tool testing themselves and publish it, they are closer to the execution path and have better data. They would be self attesting, and the argument here is that this matters, but the market may disagree, and their being wrong would not make this a business.

Ground truth cannot be made reproducible at acceptable cost. If licensing prevents even commitment based reproduction across the suites that matter, verdicts collapse into trust us, and the recursion has swallowed the fix.

## Where this stands

The method is public and runnable. The suite, the self test, the record generator, the renderer and the publication gate are in this repository to be read, run and attacked. The witness independence scale and its vectors are public. One upstream fix arising from this line of work is a public pull request against ranaroussi/yfinance making a silently suppressed price adjustment observable to the caller on every return path.

The register is built and holds records under right of reply. Nothing has been published. No relying party has paid.

The first real proof is not another standard and not another finding. It is a relying party paying for a verdict because the verdict changes what a machine is permitted to do. Until that happens, everything above is an argument, and it is published in this form so that it can be attacked before it is believed.
