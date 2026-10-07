# Local audit corrections, September 26

These changes address three reproduced paths. They do not clear the rest of the audit or establish readiness for real-money enforcement.

## Evidence attribution

`MCPStdio.call` previously appended its own explanation of a malformed `isError` flag to `protocol_noise`. The runner then used that list as a subject response excerpt. The explanation was real harness output, not words emitted by the subject.

Harness diagnostics now have their own collection. The runner's P10 recording method leaves `response_excerpt` empty when only a harness diagnostic exists, while the detail labels the interpretation as a harness diagnostic. Real non-JSON channel output remains quoted. The malformed flag remains a schema finding, not a passing result.

## Missing sessions

Counts within the old 10% tolerance, or equal counts padded by dates outside the reference window, could hide missing reference sessions. The outside-window PASS message asserted absence of missing sessions without checking the date-set difference. An existing majority-overlap test required this incorrect PASS.

For windows that meet the existing overlap threshold, the classifier now explicitly checks reference dates missing from the subject before returning PASS. Missing dates produce `partial_truncation`, with examples of those dates. A subject covering every reference date plus deeper history still passes this truncation probe; that does not establish correctness of the additional data. Low-overlap windows remain indeterminate. The former majority-overlap test now requires detection.

## Policy spelling

A misspelled top-level `limits` key was accepted and all limits silently disappeared. Unknown top-level policy keys are now refused. Malformed `limits`, rules, and `on_evidence` containers produce `PolicyError`. An explicit empty limits list remains supported. Missing limits retains the existing optional-field behavior; this patch does not require a financial-limit policy for every use case.

## Verification

`python3 suite/selftest_audit_20260926.py` runs eight test methods, including shape subcases. Against original code: exit1, five failures and three errors. Against revised code: eight test methods pass, exit0. Final tests were also rerun in a temporary tree against the backed-up original files; exit1, followed by exit0 against the fixed tree.

The full classifier suite passed389 cases after the first changes. Gateway, HTTP, observe-wrapper, live-adapter and fault-challenge checks passed. Existing recipient-check tests passed6/6 and2/2. These are offline/local checks, not a new third-party run or proof of safe inline execution.

## Publication status and remaining scope

No stored record was changed, cleared or published by this repair. The canonical checkout had no record JSON files to inspect. Read-only inspection of four records in the private mirror found no occurrence of the implicated diagnostic sentence; all four are HELD. Three have P10 PASS/OUT_OF_SCOPE results with no excerpt, and one lacks a probe list. Thus the specific claim that two of those stored records contain fabricated quotes was not reproduced. This is not a retrospective revalidation of all findings in those records.

Still open: payload-bound idempotency, wrapper enforcement timing, regex/refusal parsing, mixed unreadable OHLC handling, runner OHL-fidelity coverage, and public-render provenance. The observe wrapper must not be represented as preventing side effects of the wrapped function: it currently calls that function before evaluating the returned data. No live deployment or release is authorized by these passing tests.
