# Contributing

Start with a result someone else can reproduce. Small test cases, classifier
fixes, documentation corrections, and challenges to the method are welcome.
You do not need to test a live server to contribute.

## First run

From the repository root, with Python 3.11 or newer:

```bash
python3 examples/wrong_window.py
python3 suite/selftest.py
```

These commands use fictional fixtures and need no package installation or
credentials. The example checks three outcomes from one classifier. It does
not test a live tool or establish price correctness.

## Report a wrong result

Use the [bug-report form](https://github.com/arian-gogani/nobulex-registry/issues/new/choose)
with the smallest fictional or shareable input that
reproduces the problem. Include the exact command, actual verdict and evidence,
expected verdict and why, Python version, operating system, and repository
commit. Record the process exit code too when it is relevant.

Useful environment commands:

```bash
git rev-parse HEAD
python3 --version
```

For a method question, explain the condition the current probe cannot decide
and what evidence would let it decide. An `INDETERMINATE` outcome can be the
correct result when evidence is insufficient.

## Fixes need a failing check

Add a focused regression case and run it against the old implementation.
Actually observe the failure. Then apply the fix and run the same command
again. Report both exit codes and results in the pull request. Include a clean
control so a classifier that rejects every input cannot satisfy the test.

Keep the test while switching implementations. Use an isolated branch or
worktree and preserve unrelated work. Never discard another contributor's
changes to get a baseline. If the new test passes against the old code, it has
not demonstrated the fix. Run `python3 suite/selftest.py` after classifier or
runner changes and explain any checks you could not run.

Documentation changes should identify the corrected claim and the evidence
behind it. Do not describe unimplemented behavior as something the suite does.

## Keep reproductions public-safe

Do not put credentials, private inputs, held records, embargoed subject names,
or embargoed findings in an issue, attachment, fixture, or commit. Replace
them with fictional data before opening a public report. If that removes the
reproduction, do not upload the original. Explain the limitation without
disclosing it. Local runs are your observations, not Nobulex attestations.
