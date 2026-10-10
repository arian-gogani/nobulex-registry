"""Offline regression for the E6 consumer's primitives.

No network, no fixture clone, no third-party code executed. Everything runs
against suite/e6_vectors.json, which carries real values taken from
VeritasActa/e6-fixture v1.0.0 (commit 0770f61, Apache-2.0, Copyright 2026 Tom
Farley / Veritas Acta) and nothing else from it.

WHY VECTORS RATHER THAN THE FIXTURE. The run record posted to
aeoess/agent-governance-vocabulary#177 reports 11 of 11 agreement, and that
result is reproducible only by someone who clones the fixture. Nothing in this
repository re-checked it, so a refactor of jcs(), receipt_hash() or
merkle_root() could have broken the consumer silently and the posted claim
would have quietly stopped being true. These vectors are the smallest thing
that prevents that: 51 receipt IDs and a Merkle root, one receipt, one key
document.

WHAT THIS DOES NOT COVER, said plainly rather than left to be discovered. It
exercises the primitives, not the eleven cases. The claim functions, the
gating, the decisive rule and the runner's comparison are all unexercised here
and are checked only by running the consumer against the real fixture. A green
run of this file is not a green run of the record.
"""
import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import e6_consumer as E                                           # noqa: E402

V = json.loads((HERE / "e6_vectors.json").read_text())


class CanonicalisationAndHashing(unittest.TestCase):

    def test_receipt_id_is_jcs_over_the_whole_receipt(self):
        # Including the signature. The signature preimage is jcs(payload) and
        # these are different bytes; assuming they were the same is the first
        # thing the fixture caught.
        self.assertEqual(E.receipt_hash(V["one_receipt"]), V["receipt_ids"][0])

    def test_the_signature_preimage_is_the_payload_alone(self):
        self.assertNotEqual(E.sha256_hex(E.jcs(V["one_receipt"]["payload"])),
                            V["receipt_ids"][0])

    def test_jcs_sorts_keys_and_emits_no_whitespace(self):
        self.assertEqual(E.jcs({"b": 1, "a": [2, {"d": 3, "c": 4}]}),
                         b'{"a":[2,{"c":4,"d":3}],"b":1}')

    def test_chain_head_is_the_last_receipt_id(self):
        self.assertEqual(V["chain_head"], V["receipt_ids"][-1])


class MerkleRoot(unittest.TestCase):
    """RFC 6962 MTH over the receipt IDs, split at the largest power of two."""

    class _Fake:
        """A stand-in whose receipt_hash is a known ID, so merkle_root can be
        driven by the pinned IDs without vendoring 51 receipts."""

    def _receipts_from_ids(self, ids):
        # merkle_root calls receipt_hash on each item, so hand it objects whose
        # jcs is engineered to produce the wanted id. Simpler: monkeypatch.
        return ids

    def test_root_matches_the_signed_manifest(self):
        ids = V["receipt_ids"]
        real = E.receipt_hash
        try:
            E.receipt_hash = lambda r: r          # items ARE ids here
            self.assertEqual(E.merkle_root(ids), V["merkle_root"])
        finally:
            E.receipt_hash = real

    def test_a_single_leaf_is_hashed_not_passed_through(self):
        real = E.receipt_hash
        try:
            E.receipt_hash = lambda r: r
            one = E.merkle_root([V["receipt_ids"][0]])
            self.assertNotEqual(one, V["receipt_ids"][0])
            self.assertTrue(one.startswith("sha256:"))
        finally:
            E.receipt_hash = real

    def test_dropping_the_last_id_changes_the_root(self):
        """Case 11 in one assertion: truncation is invisible to linkage and
        visible to the root."""
        real = E.receipt_hash
        try:
            E.receipt_hash = lambda r: r
            self.assertNotEqual(E.merkle_root(V["receipt_ids"][:-1]),
                                V["merkle_root"])
        finally:
            E.receipt_hash = real

    def test_reordering_changes_the_root(self):
        real = E.receipt_hash
        try:
            E.receipt_hash = lambda r: r
            swapped = list(V["receipt_ids"])
            swapped[0], swapped[1] = swapped[1], swapped[0]
            self.assertNotEqual(E.merkle_root(swapped), V["merkle_root"])
        finally:
            E.receipt_hash = real


class Signatures(unittest.TestCase):

    def test_a_real_receipt_verifies(self):
        o, codes = E.claim_signatures({"keys": V["keys"]},
                                      [V["one_receipt"]], True)
        self.assertEqual((o, codes), (E.PASS, []))

    def test_an_edited_payload_does_not_verify(self):
        bad = json.loads(json.dumps(V["one_receipt"]))
        bad["payload"]["outcome"]["billable"] = not \
            bad["payload"]["outcome"]["billable"]
        o, codes = E.claim_signatures({"keys": V["keys"]}, [bad], True)
        self.assertEqual(o, E.FAIL)
        self.assertIn("invalid_signature", codes)

    def test_no_verifier_abstains_rather_than_passing_or_failing(self):
        # The case the fixture exists to make, and the defect this suite
        # shipped and corrected: an unreadable input scored as clean.
        o, codes = E.claim_signatures({"keys": V["keys"]},
                                      [V["one_receipt"]], False)
        self.assertEqual((o, codes), (E.ABSTAIN, ["verifier_unavailable"]))

    def test_abstain_is_not_pass_and_not_fail(self):
        self.assertNotIn(E.ABSTAIN, (E.PASS, E.FAIL, E.NOT_EVALUATED))


if __name__ == "__main__":
    unittest.main()
