# Nobulex

**The independent reliability registry for agent tools.**

Payment rails prove money moved. Nobulex proves what happened on the other side.

Starting with financial data, where correctness is checkable against an authority.

The argument underneath this, including what would make it wrong, is in [THESIS.md](THESIS.md).

[Public register](https://nobulex.com/register) · [Methodology](https://nobulex.com/methodology) · [What would make this wrong](THESIS.md)

Run the part that decides whether a verdict means anything:

```bash
git clone https://github.com/arian-gogani/nobulex-registry.git
cd nobulex-registry
python3 suite/selftest.py
```

No package install is required for the self-test. If you find a corrupted response it calls clean, open an issue with the smallest reproduction you can make. If you want to follow the work, star the repository.

### Try one failure in a minute

```bash
python3 examples/wrong_window.py
```

This offline example feeds fictional data into the suite's actual truncation classifier. It shows three cases: matching sessions (`PASS`), silently missing sessions (`FAIL_UNSAFE`), and equal row counts covering entirely different dates (`INDETERMINATE`). The last case passes a count-only comparison, but this probe cannot establish a clean result from it.

The script checks all three expected outcomes and exits nonzero if any changes. It needs only Python 3.11 or newer. No credentials or downloads are needed after cloning. This demonstrates one classifier, not a live tool test or a registry attestation. Even its `PASS` does not establish that the prices are correct.

Found an input that produces the wrong verdict? [Open an issue](https://github.com/arian-gogani/nobulex-registry/issues/new/choose) with fictional or shareable input, the command you ran, the actual output, and the result you expected. Please leave credentials and private data out.

Want to contribute a test, fix, or method correction? Start with [CONTRIBUTING.md](CONTRIBUTING.md).

---

## The failure this exists for

An agent calls a tool. The tool returns a response that is well formed, plausible, and materially wrong.

Empty where it should have been populated. Stale where it claims to be current. Scoped to a different entity than the one requested. Truncated with no signal that anything was cut. Filled from a fallback path that was never disclosed.

Nothing raises. Nothing logs. The schema validates, because a well formed lie validates perfectly. The agent has no way to distinguish this from a correct answer, so it acts on it, and every downstream step inherits the error with full confidence.

This registry has one subject: **silent semantic corruption**.

The governing test is one question:

> **Does it fail loud, or does it lie quiet?**

A tool that raises an error is usable. You can retry it, route around it, surface it to a human. A tool that returns a confident wrong answer is not usable, and it is not currently measured by anything. Uptime does not measure it. Stars do not measure it. A green CI badge does not measure it. Schema validation does not measure it. Latency percentiles do not measure it.

Every existing reliability signal in this ecosystem answers "did it respond." None of them answer "was the response true."

## Why financial data first

Not because it is the largest market. Because it is the only place where the ground truth is unambiguous, timestamped, and independently obtainable. A stock price at a given second either matches an authority or it does not. There is no rubric, no judgment call, and no argument about whether the verdict was fair.

Categories where correctness is a matter of opinion come later, or never. A registry that starts somewhere contestable spends its first year defending verdicts instead of accumulating them.

---

## What gets graded

Never a project. Never a company. Never a name on a repository.

The subject of a Nobulex record is a **tuple**, and every field in it is load bearing:

- **package** identity
- **exact version or commit SHA**, never a floating tag or branch
- **configuration** used during the run
- **upstream data source** the tool was reading from
- **execution environment**
- **test suite** identifier and version
- **observation time**

Drop any one field and the record stops being reproducible, which means it stops being evidence. A grade attached to "acme-mcp" is a rumor. A grade attached to `acme-mcp @ 3f21b09, config X, upstream Y, env Z, suite v0.2, observed 2026-08-02T14:11Z` is a record.

This is also the defamation boundary. Nobulex grades a commit under stated conditions. It does not characterize a company, a maintainer, or a product line.

---

## The five verdicts

| Verdict | Meaning |
|---|---|
| `PASS` | Under this suite, in this window, the subject returned results correct within a tolerance pinned before execution, against a named ground truth source. |
| `FAIL_SAFE` | The subject failed, and the failure was loud. Errors raised, degradation disclosed. Recoverable, and still a failure. |
| `FAIL_UNSAFE` | The subject returned a well formed answer that was materially wrong, with no signal. This is the category. |
| `INDETERMINATE` | The run could not establish either result. Harness fault, upstream outage, insufficient ground truth. Not a soft fail. |
| `OUT_OF_SCOPE` | The suite does not cover this subject's behavior under these conditions. No claim is made in either direction. |

Two rules that are not negotiable:

**`FAIL_SAFE` is better than `FAIL_UNSAFE`, and it is not the same as `PASS`.** A tool that is down and says so has left you something to route around. It is still failing. Anyone who reads `FAIL_SAFE` as a pass has been told something false, and the presentation layer is responsible for preventing that reading.

**`INDETERMINATE` is a real verdict, not an absence.** A registry that quietly drops the runs it could not resolve is publishing a survivorship curve, not evidence. Indeterminates get recorded, counted, and shown.

---

## Three attestation types, never merged

- **TOOL** attestation covers one subject tuple called directly, with no model in the loop.
- **COMPATIBILITY** attestation covers whether a specific client reads the tool's description and schema correctly, which is a different failure from the tool returning bad data.
- **WORKFLOW** attestation covers a model, client, server, configuration, and task executing end to end.

These answer different questions and carry different warranties. The reason they stay separate is not tidiness. It is that merging them lets a vendor dispute whose fault a failure was: the model misread the description, the client mangled the call, the server returned garbage. Three separate records make that argument unavailable.

Averaging them into a single number is how a registry becomes a star rating, and a star rating is exactly the signal that already exists and already fails.

---

## What a verdict warrants, and what it does not

A Nobulex record **does** say:

- These specific inputs were sent to this exact subject tuple at this time.
- These outputs came back.
- They were compared against this named ground truth source.
- Deviations were classified under this published taxonomy.
- Anyone with the record can rerun the suite and get the same result.

A Nobulex record **does not** say:

- That the subject is safe, secure, or free of vulnerabilities.
- That the subject is fit for your use case.
- That the subject will behave the same way tomorrow, or on a different commit, or against a different upstream.
- That the maintainer is trustworthy or untrustworthy.
- Anything at all in a currency. Nobulex publishes no dollar-denominated trust figure, no coverage limit, and no score that looks like one.

Nobulex is the **evidence provider, not the custodian.** It holds no funds, insures nothing, and settles nothing. Where a remedy is warranted, that is a licensed counterparty's product, and the record is the input to it.

---

## Validity windows and expiry

Records carry validity metadata. The current runner assigns a seven-day window to results that do not require right of reply. Results held for reply initially have no expiry deadline; clearing assigns a seven-day window when one is missing.

The current register displays the stored verdict and its validity deadline. It does not automatically change the displayed verdict to `EXPIRED` when that deadline passes. Readers must check the deadline, and a historical `PASS` must not be treated as evidence of current behavior.

Automatic expiry at lookup is intended behavior, not implemented enforcement in this register. The stored observation remains historical evidence; whether it is still current needs a separate check.

Correction: this section previously claimed that an out-of-window query returns `EXPIRED` and that the schema cannot represent an expired pass. The current implementation does not support those claims.

**There will never be a portable badge image.** A PNG a maintainer can copy into a README is a claim that outlives its evidence, keeps rendering green after the verdict is withdrawn, and cannot be revoked. That mechanism is the specific way this category of business has failed before. Verification resolves against the register, live, or it does not resolve.

---

## Who pays

**The party relying on the verification pays. Never the graded party for its own verdict or re-test.**

A maintainer cannot commission a verdict on its own package, cannot preview one before publication, and cannot negotiate one. The moment revenue depends on the subject's satisfaction, every verdict becomes a negotiation, and the registry's output is worth precisely nothing. This constraint costs real money early. It is what the entire thing is made of.

Maintainers can submit fixes and evidence for review, but cannot buy a re-test of their own tool. Re-tests follow the published methodology and retain the same funding separation.

Correction: this README previously allowed maintainer-funded re-tests. That exception contradicted the buyer-funded policy stated on the site. It is removed here. This is a policy correction, not evidence that any paid re-test took place. Independent verification also requires reproducible evidence and a checkable method; the funding rule alone does not establish it.

---

## What is sold

Two things, neither of which is the public register.

**Buyer-pinned verification.** You name the server and the exact release you intend to deploy, plus the conditions you require: which upstreams, which configuration, which tolerance, which environment. Nobulex tests that tuple independently and returns a procurement-ready attestation. This is the first paid product, because it is the only one where somebody has already decided to spend money and needs a reason to sign.

**Continuous verification.** A pass three months ago says nothing about today. Upstreams change shape, maintainers ship, adapters absorb drift silently. Continuous verification re-runs the pinned suite against the pinned subject on a schedule and alerts when the verdict changes. This is the recurring product, and it is the one that matters most, because it is the only version of this that keeps being true.

The public register is the distribution surface for both. It is marketing. It is not the business, and confusing the two is how registries with beautiful dashboards run out of money.

---

## The loss cause taxonomy

Every deviation is classified before it is recorded. The taxonomy is versioned from the first record it is applied to, because a classification scheme that changes silently makes its own history unreadable.

`v0` covers:

| Code | Failure |
|---|---|
| `silent_empty` | Returned an empty result where data existed, with no signal. |
| `stale_value` | Returned cached or outdated data presented as current. |
| `wrong_entity` | Returned data for a different entity than the one requested. |
| `fabricated_field` | Returned a field populated with a value that has no upstream basis. |
| `partial_truncation` | Returned a subset of the result with no truncation signal. |
| `unsignaled_fallback` | Served from a fallback source without disclosing the substitution. |
| `auth_degradation` | Silently downgraded to a lower privilege tier and returned reduced data as complete. |
| `schema_drift` | Upstream shape changed and the adapter absorbed it into a wrong but valid response. |

Each code is designed to be decidable from a run artifact without a human judgment call, which is what keeps the corpus consistent as it grows.

The accumulated history of which subjects fail in which ways is the part of this that cannot be reconstructed later. Anyone can copy the taxonomy in an afternoon. Nobody can copy three years of observations they did not make.

---

## Status

Written plainly, because a registry whose README overclaims has already failed its own test.

**Designed and specified:** the verdict system, the subject tuple, the attestation types, the loss cause taxonomy v0, the warranty scope, the expiry model, the publication gate, and the public register surface.

**Built:** a verification harness that speaks raw JSON-RPC to a subject over stdio and never imports the subject's own code, with probes for nonexistent entities, malformed input, closed-market dates, OHLC invariants, monotonic dates, silent truncation, cross-endpoint agreement, and freshness against an independent authority. A self-test that runs those probes against fixtures known to be bad, because a probe that cannot fail is worse than no probe at all. A record generator that writes the subject tuple from the environment the run actually happened in rather than from what the subject reports about itself, since a subject that self-reports its version can be wrong about it, and one of them was. A register page compiled from the records on every build, with a check mode that fails when the page and the records disagree. A publication gate that keeps a held record off the public page by construction, and refuses to write the page at all if a held record's identifier or its subject's name reaches it by any path. Held records themselves live outside version control, and what is committed in their place is a manifest that fixes each one by sha256 without disclosing a word of what it says, so a record can be unalterable and unreadable at the same time.

**Run:** the suite has been run live against a pinned commit of a third party MCP server, twice, under two separately resolved dependency sets for the same source code. Each run produced a record. Both records are held under right of reply, and what they found is not stated here, for the same reason it is not stated on the register: a finding its subject has not yet seen is not one they can answer.

**Not yet true:**

- **Nothing is published.** Every record this registry has issued is held, the notices to their subject are written and unsent, and no reply window has opened. The register today carries its rules and a count of what is being withheld, and no subject at all. A registry that has issued verdicts and published none of them has not yet done the thing it exists to do.
- **No verdict here is checkable by a stranger yet.** The method is, as of this repository: the harness, the probes, the self-test, the record generator, the renderer and the publication gate are all here to be read, run, and attacked. The records are not, because every one of them is held. Until the first one publishes, anything this project says about what it found is a claim about runs that exactly one machine has seen, and an uncheckable verdict is an opinion with a logo on it.
- **There is no persistent issuing identity.** Records are not signed by a key with durable, publicly anchored provenance, and until they are, a signature proves only that the same ephemeral key signed twice.
- **No buyer has paid for a verification.** Nobody has stated what they would pay, or at what point in their process they would want it.

The first record this registry ever issued was withdrawn, because its subject tuple named a version that could not be resolved to anything real. The withdrawal was not deleted and will not be, because a registry that erases its mistakes is asking to be trusted instead of checked. It is not on the register today either, and the reason is worth stating: it is about the same package as the two records under reply, and it is the only subject the page would name at all, so publishing it tells a reader that findings are being withheld about one identified project while showing none of the evidence. That is the accusation the reply window exists to prevent, delivered without the detail its subject would need to answer it. It publishes on the day its successors do.

Those four gaps are the actual state of this project. Everything above is the design they are being built toward.

---

## Run it

Python 3.11 or newer. No dependencies for the self-test.

```
python3 suite/selftest.py
```

That is the first thing worth running and the first thing worth attacking. It runs every classifier in the harness against fixtures that are known to be bad and against fixtures that are known to be clean, and it fails if a classifier misses a planted failure or fires on clean input. A probe that cannot fail is worse than no probe at all, so the self-test is the part of this repository that decides whether any verdict it issues means anything. If you can construct a corrupted response that the suite calls clean, that is a bug in the registry and it is the most useful thing you could send.

To run the suite against a live subject, clone the subject yourself, at a commit you pin, into an environment you resolved:

```
python3 suite/run.py --subject-dir <path-to-subject> --python <path-to-its-interpreter> --entry server.py \
  --upstream "<the service the subject reads from>" \
  --tool-history <tool that returns price bars> --tool-info <tool that returns entity metadata>
```

The harness speaks raw JSON-RPC over stdio and never imports the subject's code, because a harness that imports its subject is measuring a process it is also part of. The subject tuple in the resulting record is read from the environment the run actually happened in and not from what the subject says about itself.

`--python` accepts an executable path or a command on your `PATH`, such as `python3`. Relative paths are resolved from the directory where you invoke the runner, before it switches to the subject directory. Use the subject's own environment, with its dependencies already installed. A missing or nonexecutable interpreter is refused with exit code 2 before any probes run or a record is written. Correction: the runner previously treated a bare command as a local filename and let invalid interpreter paths reach subject inspection.

`--subject-dir` must be an existing directory. `--entry` is resolved relative to that directory, or may be an absolute path. A missing entry is refused with exit code 2 before observations or recording. Correction: a typo in the entry path previously produced a `COMPATIBILITY` record with a `FAIL_SAFE` startup finding, even though the named script did not exist. This preflight checks paths, not whether the existing subject can start or has working dependencies.

`--upstream` is required and has no default, which is deliberate. Every other field of the tuple is read off the run: the package from the directory, the commit from git, the resolved dependencies from the interpreter you pointed at. That one cannot be, because a server does not have to say where its data comes from and can be wrong when it does. A default there would be a value the record asserts and nobody observed, which is `fabricated_field`, which is one of the eight causes this suite grades other software for. It was a hardcoded string here until it was caught, and it is named in this paragraph rather than quietly fixed because a registry that hides its own defects has no standing to publish anyone else's.

`--tool-history` and `--tool-info` are required for a worse reason, and it is worth reading before running anything. The probes call the subject by tool name. A name the subject does not expose comes back as a protocol error, and a protocol error is what several of these probes count as *correct* behavior: a tool that refuses a nonexistent ticker through the error channel has passed P01 by design. So a run pointed at a subject that does not have these tools answered PASS on four probes, on evidence that consisted entirely of the tools not being there, and wrote a record with a full subject tuple that looked exactly like a real one. That is a verdict that fails quiet, produced by the suite whose only purpose is to catch verdicts that fail quiet.

The names used to be hardcoded, so this could only happen to someone pointing the suite at their own server, which is the first thing this README tells a stranger to do. The names are now supplied by the operator and checked against the subject's own `tools/list` before a single probe runs, so every error a classifier sees afterward is the subject refusing a question it was actually asked. Run without the flags and the harness prints the tools the subject does expose, then exits without writing a record. The aggregate verdict in that scenario was `INDETERMINATE` rather than `PASS`, because the data-comparison probes had no bars to compare and `INDETERMINATE` dominates `PASS`, so the damage was bounded. Four probe-level PASSes on a subject that was never tested is still the wrong answer, and it is written down here rather than fixed quietly.

The record is written to `--out`, numbered one past the highest number already there. Numbers are never reused, including by records that were withdrawn, and a run whose number is already taken is refused before the first probe rather than allowed to overwrite what is on disk. A record id is an identity that other documents cite, so overwriting one would destroy the evidence while leaving every reference to it resolving, which is the exact shape of failure this suite exists to catch.

### Check that the published page has one author

`brand/register.html` in this repository is the file that is served at `https://nobulex.com/register`. Not a copy of it, not a version of it. The same bytes.

```
shasum -a 256 brand/register.html
curl -sS https://nobulex.com/register | shasum -a 256
```

Both should print `c3608fd261e046adf15cd14760f39e65c18c62f3c6b7a689182c82e267fdc783` after deployment of the expiry-copy correction.

Correction provenance: the expiry explanation was changed in the template and identically in the committed and website HTML copies, without rerendering held records. The local copies were compared byte for byte. This was a direct static-copy correction, not a fresh record build; the command above independently checks the deployed copy.

This is worth two minutes because it is the one claim on this project that a stranger can settle right now, without waiting on a reply window and without taking anyone's word for anything. The register is compiled from the records by `suite/render_register.py`, which writes identical bytes to every publish target in one build, specifically so that no hand can reach the page between the records and the reader. A downstream copy step is a second author, and a second author of that page is a second chance to publish a name that is under embargo. If those two hashes ever disagree, something edited the published page after the generator produced it, and you should say so loudly.

The hash will change whenever the register legitimately changes, which today means when a record publishes. The value above is the current one.

### Rebuild the register

```
python3 suite/render_register.py
```

On a clone this refuses and writes nothing. The held records are not in version control and the held count on the page is compiled from them, so building here would replace a page stating that three records are held with one stating that none are, which reads as findings having been quietly dropped. The refusal names the records the manifest commits to and could not read. Rebuilding is meaningful where the records live; the hash comparison above needs no rebuild, which is why it is the check a stranger can run.

That refusal is recent. Until it existed the generator built happily in a clone and overwrote the page with a zero count, and the README called that diff expected and told you to `git checkout` it back. It is the same defect this suite exists to find in other people's tools, in this one: an input that could not be read, counted as agreement.

The generator refuses at build time to write a page carrying a held record's identifier, a held subject's name, or a verdict token in the embargo block, and refuses to build at all from a checkout that cannot read every held record the manifest commits to. Those refusals are in `suite/render_register.py` where the conditions can be read rather than taken on trust.

---

## The register

The test suite is the product. The register is where its results are published.

A record is a reproducible, independently checkable object with a subject tuple, a verdict, a loss cause classification, a validity window, and a suite reference. Anyone will be able to pull it, rerun it, and disagree with it in public. If a record cannot be independently reproduced by a stranger, it was never evidence, and it does not belong in the register.

---

## Right of reply

Before any record with an adverse finding is published, the maintainer of the subject receives the full run artifact and has seven days to respond. The reply is published alongside the record, unedited. Adverse means `FAIL_UNSAFE`, `FAIL_SAFE`, or `INDETERMINATE`: any verdict that says in public that a named person's software did not do what it should.

This used to say `FAIL_UNSAFE` only, and the narrower rule was wrong twice over. It was wrong on the merits, because a `FAIL_SAFE` record still tells the world that someone's project is broken, and severity is not what earns a subject the right to be heard; being publicly criticised by a stranger is. It was also wrong mechanically. The register says how many records it is holding, and if the only records ever held were `FAIL_UNSAFE`, then saying "one record is held" published the verdict without publishing the evidence. A finding a reader can infer but nobody can check is worse than one that is fully published, because there is nothing for the subject to answer.

The register may say that a record is held and how many are held. It may not say what a held record found, not even its verdict, and it may not name who the record is about.

The second half of that rule was learned the hard way, one layer down from the first. Stripping the verdicts was not enough. The page still named a subject elsewhere, and the page still said records were being held under right of reply, and right of reply now covers every adverse verdict, so those two published facts join into a third that was never written anywhere: a named project has an adverse finding against it that nobody can see. Whether a verdict token appears on the page is beside the point. The identity is part of the finding, so while any record is held, the register names no held subject at all. Today that means it publishes no subject whatsoever, which is the true state of a registry whose every record is waiting on someone else. The renderer refuses to write the page if a held subject's name reaches it, in the same way it already refuses on a held record's identifier.

Each held record is committed to by sha256 in a manifest that is in version control while the record itself is not. When one publishes, anyone can hash it and check it against the value committed the day it was issued. That is what turns "the verdict was fixed before the window opened, and nothing was quietly softened while the subject was drafting a reply" from something the registry asserts into something a stranger can check. It is not a formal commitment scheme, since there is no nonce and it leans on the record's own entropy, and it is not a timestamp, since the commit date is worth exactly what the person who set it is worth. Both of those are gaps, and they are listed as gaps rather than papered over.

The reply is **not adjudicative.** It cannot alter the verdict, and no part of it is negotiated. The verdict describes what the suite observed under pinned conditions, and the only thing that produces a different verdict is a different run: a new commit, or new conditions, pinned and executed again. The request, the delivery, and the reply window are all logged as part of the record.

This exists because publishing a failure without giving the subject a voice is how a registry becomes a liability, not because the subject gets a vote.

---

## Why this repository's history begins at one commit

The work happened in a private repository, and its earlier commits carry the held records in full, verdict field and all. Removing a file from the working tree does not remove it from the commits that already carry it, and the commits are what a clone hands over. Pushing that history would have published every held record at the moment the repository went public, which ends three reply windows before any of them opened. So the public repository starts from a fresh history containing the method and nothing else.

That has a cost, and it should be stated rather than discovered. The point of `records/held.manifest.json` is that when a held record publishes, a stranger can hash it and check it against the commitment made on the day it was issued. A fresh history moves the public anchor to the day this repository was pushed, not the day the records were written. For the three records held today, the earlier commitment exists only in a private history, which is worth exactly what its author is worth, which is the same problem as the commit date and is listed alongside it. From this commit forward the anchor is public and the check is real. For what is already held, it is not, and no amount of explaining makes it so.

The alternative was to rewrite the affected commits and push a laundered history, which is a worse answer from a project whose entire claim is that it says what it found.

---

## The push is where a hold survives or does not

Every other gate here protects a derived artifact. The renderer refuses to write a page naming a held record or a held subject, and that was worth building, and it protects one file. A push hands over the whole repository. The first time this one was ready to go public, three commits carried two held records in plain text with the verdict field intact, and the rendered page was clean the entire time.

So there are two hooks in `hooks/`, and they are not the same hook, because the two repositories have opposite obligations. In the working repository a held record must be present and must hash to the value committed for it, and its absence is the fault. In the public repository the same file must be absent, and its presence is the leak. `hooks/pre-push` checks the first. `hooks/pre-push-export` checks the second: that nothing the manifest commits to is on disk, that no record arrived by a path the renderer did not compile, that the number of held records the register states matches the number the manifest backs, that no held record is reachable from any commit, and that the suite passes in the copy a stranger would clone rather than only in the one it was written in.

That second hook exists because of a defect found while going to install the first one. The working repository has no remote, so its push hook guards a repository that can never hand anything to anybody. The public repository has the remote, and there every check in that hook fails by construction: it verifies records that are correctly missing, and it recompiles a register that cannot be recompiled without them. Installing it there would have refused every push forever, which is why it had been installed in neither place. The guard could not fire where it could run and could not run where it was needed. That is the same shape as the other defects listed here, which is a gate applied to the artifact it was written for and to nothing else that discloses, and it is written down for the same reason they are.

The history walk in the export needed one further correction along the way. It takes the record identifiers it searches for from the held records, and the export has none, so it was searching for nothing and would have reported clean on any repository whatsoever. It now reads them from the manifest, which carries them on purpose: an identifier with no verdict attached is not a disclosure, and that is exactly why the register is permitted to say a record is held and not permitted to say what it found.

Both hooks can be bypassed with `--no-verify`. That is deliberate. A guard that cannot be overridden gets deleted the first time it is inconvenient, and what matters is that going around it is a sentence somebody typed on purpose rather than something that happened to them.

Git does not install hooks from a repository, so a clone gets an inert copy of both until somebody wires one up, and an inert guard reads exactly like a guard. In the public repository:

```
cp hooks/pre-push-export .git/hooks/pre-push && chmod +x .git/hooks/pre-push
```

and in a working repository that holds records, `hooks/pre-push` instead. Running the wrong one is loud in either direction, because each refuses on precisely the state the other requires.

---

## License

MIT. See [LICENSE](LICENSE).

The suite is open source because a verdict derived from a suite nobody can read is not evidence. Anyone can run it against anything, including against the subjects this registry has graded, and reach a different answer in public. That is the intended use. What is not transferable is the record: a verdict is an entry in the register with a full subject tuple behind it, and running the suite yourself produces your result, not a Nobulex one.
