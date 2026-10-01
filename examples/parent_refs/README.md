# Signed parent-reference vectors

Run the generators and checks from the repository root:

```sh
python3 examples/parent_refs/build_fixture.py
python3 examples/parent_refs/build_coverage_vector.py
python3 examples/parent_refs/test_causal_coverage.py
```

Vectors 04 and 05 test different sides of the fan-in limit. Vector 04 records
that this constructor refused 65 parents. Vector 05 is a validly signed
65-parent receipt made without that constructor; the verifier rejects it.
The constructor alone does not protect against a hostile producer.

Vector 06 is a signed three-record graph: two roots and one action joining
them. A fan-in verifier returns `COMPLETE` only after verifying both roots.
A single-parent-only verifier returns `INCOMPLETE` with
`fan_in_unsupported`. Missing records and traversal limits also return
`INCOMPLETE`; a bad signature, key-to-record mismatch, or cycle returns
`REFUSED`. The result states whether the supplied signed graph was fully
traversed. It cannot establish that every real-world action was recorded.

The fixture uses a fixed published Ed25519 key for reproducibility. The
signature authenticates only that fixture key, not any production actor.
Its JSON serialization matches RFC 8785 for the values used here but is not
a general RFC 8785 implementation; see `build_fixture.py` for the limits.
