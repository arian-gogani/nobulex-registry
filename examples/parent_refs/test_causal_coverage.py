#!/usr/bin/env python3
"""A joined execution is complete only when every signed parent reaches a root."""

import unittest
import json

from build_fixture import _signer, build_receipt
from causal_coverage import reconstruct
from build_coverage_vector import OUT, make_vector


class CausalCoverageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sign, cls.key = _signer()
        if cls.sign is None:
            raise RuntimeError("cryptography is required; coverage was not tested")
        cls.left = "sha256:" + "a1" * 32
        cls.right = "sha256:" + "b2" * 32
        cls.join = "sha256:" + "c3" * 32
        cls.records = {
            cls.left: build_receipt(cls.left, [], cls.sign),
            cls.right: build_receipt(cls.right, [], cls.sign),
            cls.join: build_receipt(cls.join, [cls.right, cls.left], cls.sign),
        }

    def test_every_branch_reaches_a_root(self):
        result = reconstruct(self.records, self.join, self.key)
        self.assertEqual(result["status"], "COMPLETE")
        self.assertEqual(result["roots"], [self.left, self.right])
        self.assertEqual(result["visited"], 3)

    def test_single_parent_only_verifier_declares_limit(self):
        result = reconstruct(self.records, self.join, self.key,
                             fan_in_supported=False)
        self.assertEqual(result["status"], "INCOMPLETE")
        self.assertEqual(result["reason"], "fan_in_unsupported")
        self.assertNotEqual(result["status"], "COMPLETE")

    def test_missing_other_branch_is_not_a_complete_chain(self):
        records = {k: v for k, v in self.records.items() if k != self.right}
        result = reconstruct(records, self.join, self.key)
        self.assertEqual(result["status"], "INCOMPLETE")
        self.assertEqual(result["reason"], "missing_parent")

    def test_depth_limit_is_not_a_complete_chain(self):
        result = reconstruct(self.records, self.join, self.key, max_depth=0)
        self.assertEqual(result["status"], "INCOMPLETE")
        self.assertEqual(result["reason"], "depth_limit")

    def test_ancestor_budget_is_not_a_complete_chain(self):
        result = reconstruct(self.records, self.join, self.key,
                             max_ancestors=1)
        self.assertEqual(result["status"], "INCOMPLETE")
        self.assertEqual(result["reason"], "ancestor_limit")

    def test_ref_key_mismatch_is_refused(self):
        records = dict(self.records)
        records[self.right] = build_receipt("sha256:" + "dd" * 32, [],
                                            type(self).sign)
        result = reconstruct(records, self.join, self.key)
        self.assertEqual(result["status"], "REFUSED")
        self.assertEqual(result["reason"], "action_ref_mismatch")

    def test_cycle_is_refused(self):
        records = dict(self.records)
        records[self.left] = build_receipt(self.left, [self.left],
                                           type(self).sign)
        result = reconstruct(records, self.join, self.key)
        self.assertEqual(result["status"], "REFUSED")
        self.assertEqual(result["reason"], "cycle")

    def test_changed_signed_parentage_is_refused(self):
        records = json.loads(json.dumps(self.records))
        records[self.join]["parent_refs"] = [self.left]
        result = reconstruct(records, self.join, self.key)
        self.assertEqual(result["status"], "REFUSED")
        self.assertIn("preimage_sha256", result["reason"])

    def test_bad_signature_is_refused(self):
        records = json.loads(json.dumps(self.records))
        records[self.join]["signature"]["sig"] = "AA=="
        result = reconstruct(records, self.join, self.key)
        self.assertEqual(result["status"], "REFUSED")
        self.assertIn("signature does not verify", result["reason"])

    def test_published_fixture_is_current(self):
        self.assertEqual(json.loads(OUT.read_text()), make_vector())

    def test_refusal_record_does_not_claim_attacker_cannot_sign(self):
        record = json.loads((OUT.parent /
                             "04-fan-in-cap-exceeded.REFUSAL.json").read_text())
        self.assertEqual(record["scope"], "conforming producer only")
        self.assertEqual(record["signed_adversarial_vector"],
                         "05-fan-in-cap-exceeded.SIGNED-ADVERSARIAL.json")


if __name__ == "__main__":
    unittest.main()
