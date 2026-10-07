"""Offline regression of five defects where a check ran but judged nothing.

No subject process, no dependency install, no network. Classifiers and the
policy validator are exercised directly.

The five share one shape: a guard that was correct about the question it asked
and was asked the wrong question. Three were lexical tests standing in for
structural ones (a substring for a refusal, a substring for membership), and two
were type guards that admitted a value the comparison could not order (a string
price, a bool notional). In every case the defect was not a missing check. It
was a check whose result did not mean what the evidence beside it said.

Each test carries its own control, because a test that only pins the failing
input cannot tell a fix from a function that now refuses everything.
"""
import json
from pathlib import Path
import runpy
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "gateway"))
import harness                                                    # noqa: E402
import decide                                                     # noqa: E402

POLICY = json.loads((HERE.parent / "gateway" / "policy.example.json").read_text())
CLEAN_CTX = {"evidence": {"quote": {"age_ms": 50, "deviation_bps": 1}},
             "portfolio": {"daily_turnover_pct": 1}}


def ctx(**action):
    return dict(CLEAN_CTX, action=action)


class InvalidArgumentTier(unittest.TestCase):
    """A payload that carries records is an answer, whatever words sit in it."""

    def test_error_key_in_an_ordinary_bar_is_not_a_refusal(self):
        # A struct serialized without omitempty. "error": null is not prose.
        bars = [{"Date": "2026-09-12", "Close": 241.1, "error": None}] * 3
        o, c, _ = harness.classify_invalid_argument(
            json.dumps(bars), False, bars, "interval='banana'")
        self.assertEqual((o, c), ("FAIL_UNSAFE", "unsignaled_fallback"))

    def test_substring_error_inside_a_word_is_not_a_refusal(self):
        bars = [{"Date": "2026-09-12", "Close": 241.1,
                 "longName": "Terror Systems Inc"}]
        o, _, _ = harness.classify_invalid_argument(
            json.dumps(bars), False, bars, "interval='banana'")
        self.assertEqual(o, "FAIL_UNSAFE")

    def test_control_a_real_prose_refusal_with_no_records_is_fail_safe(self):
        o, _, _ = harness.classify_invalid_argument(
            "Error: invalid interval", False, [], "interval='banana'")
        self.assertEqual(o, "FAIL_SAFE")

    def test_control_the_error_channel_still_wins(self):
        o, _, _ = harness.classify_invalid_argument(
            "", True, None, "interval='banana'")
        self.assertEqual(o, "PASS")


class DeliveredPriceIsAnAnswer(unittest.TestCase):
    """The verdict tier must not depend on the subject's JSON encoder."""

    ABSENT = "ZZZZQQ"

    def _fab(self, **over):
        base = {"Date": "2026-09-12", "Open": 241.00, "High": 242.10,
                "Low": 240.50, "Close": 241.10, "sector": "Unknown"}
        base.update(over)
        return [base]

    def test_string_serialized_prices_are_still_prices(self):
        p = self._fab(Open="241.00", High="242.10", Low="240.50",
                      Close="241.10")
        self.assertFalse(harness._said_absent(json.dumps(p), p))
        o, c, _ = harness.classify_absent_entity(json.dumps(p), False, p)
        self.assertEqual((o, c), ("FAIL_UNSAFE", "fabricated_field"))

    def test_an_unlisted_price_key_spelling_is_still_a_price(self):
        for key in ("Adj Close", "adjclose", "adj_close", "price"):
            with self.subTest(key=key):
                p = [{"Date": "2026-09-12", key: 241.1, "sector": "Unknown"}]
                o, _, _ = harness.classify_absent_entity(
                    json.dumps(p), False, p)
                self.assertEqual(o, "FAIL_UNSAFE", f"{key} was not read")

    def test_control_numeric_prices_were_always_correct(self):
        p = self._fab()
        o, c, _ = harness.classify_absent_entity(json.dumps(p), False, p)
        self.assertEqual((o, c), ("FAIL_UNSAFE", "fabricated_field"))

    def test_control_a_payload_with_no_price_is_still_read_as_a_refusal(self):
        p = [{"error": "not found"}]
        o, _, _ = harness.classify_absent_entity(json.dumps(p), False, p)
        self.assertEqual(o, "FAIL_SAFE")

    def test_control_a_non_numeric_string_under_a_price_key_is_not_a_price(self):
        """Close: "unavailable" is a refusal, not a delivered price."""
        p = [{"Date": "2026-09-12", "Close": "unavailable"}]
        self.assertFalse(harness._delivered_prices(p))

    def test_control_bool_is_not_a_price(self):
        self.assertFalse(harness._delivered_prices([{"Close": True}]))


class OhlcNullAndUnreadable(unittest.TestCase):
    """"Skipped as null" must not be said about a bar that was unreadable."""

    GOOD = {"Date": "2026-07-28", "Open": 300.0, "High": 305.0,
            "Low": 299.0, "Close": 304.0}

    def test_a_bar_both_null_and_unreadable_is_indeterminate(self):
        # Low "10" is above High "9" and neither is comparable as a string.
        bad = {"Date": "2026-09-02", "Open": 5.0, "High": "9",
               "Low": "10", "Close": None}
        o, _, ev = harness.classify_ohlc([self.GOOD, bad])
        self.assertEqual(o, "INDETERMINATE")
        self.assertNotIn("internally consistent", ev)

    def test_control_a_plain_partial_null_is_still_skipped_not_punished(self):
        ok_null = {"Date": "2026-09-02", "Open": 5.0, "High": 9.0,
                   "Low": 4.0, "Close": None}
        o, _, _ = harness.classify_ohlc([self.GOOD, ok_null])
        self.assertEqual(o, "PASS")

    def test_control_a_surviving_inequality_under_a_null_still_fails(self):
        violating = {"Date": "2026-09-02", "Open": 5.0, "High": 9.0,
                     "Low": 400.0, "Close": None}
        o, c, _ = harness.classify_ohlc([self.GOOD, violating])
        self.assertEqual((o, c), ("FAIL_UNSAFE", "fabricated_field"))


class OperandTypeMustSuitOperator(unittest.TestCase):

    def _pol(self, **rule):
        base = {"field": "action.symbol", "op": "in",
                "value": ["AAPL", "MSFT"], "code": "SYM"}
        base.update(rule)
        return {"id": "t", "version": "1",
                "on_evidence": {"PASS": "PERMIT", "FAIL": "BLOCK",
                                "INDETERMINATE": "ESCALATE"},
                "on_limit_violation": "BLOCK", "limits": [base]}

    def test_in_with_a_string_operand_is_refused(self):
        with self.assertRaises(decide.PolicyError) as cm:
            decide.validate_policy(self._pol(value="AAPL,MSFT"))
        self.assertIn("substring", str(cm.exception))

    def test_an_ordering_limit_against_a_non_number_is_refused(self):
        for bad in ("50000", None, True, [1]):
            with self.subTest(value=bad):
                with self.assertRaises(decide.PolicyError):
                    decide.validate_policy(
                        self._pol(field="action.notional_usd", op="lte",
                                  value=bad, code="NOTIONAL"))

    def test_control_an_array_operand_validates_and_discriminates(self):
        pol = self._pol()
        decide.validate_policy(pol)
        self.assertEqual(
            decide.decide(pol, ["PASS"], {"action": {"symbol": "AAPL"}})
            ["decision"], "PERMIT")
        # "A" is a substring of "AAPL" and must not be a member of the array.
        self.assertEqual(
            decide.decide(pol, ["PASS"], {"action": {"symbol": "A"}})
            ["decision"], "BLOCK")

    def test_control_the_shipped_example_policy_still_validates(self):
        decide.validate_policy(POLICY)


class ObservedValueMustBeAQuantity(unittest.TestCase):

    def test_a_bool_notional_does_not_satisfy_a_cap(self):
        for v in (True, False):
            with self.subTest(notional=v):
                d = decide.decide(POLICY, ["PASS"], ctx(notional_usd=v))
                self.assertNotEqual(d["decision"], "PERMIT")

    def test_a_bool_notional_is_unevaluated_not_violating(self):
        d = decide.decide(POLICY, ["PASS"], ctx(notional_usd=True))
        self.assertGreater(d["unevaluated_limits"], 0)
        codes = [r for r in d["reasons"] if r.get("status") == "UNEVALUATED"]
        self.assertTrue(codes, "a bool must be reported unevaluated")

    def test_nan_and_inf_are_not_quantities(self):
        for v in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(notional=v):
                d = decide.decide(POLICY, ["PASS"], ctx(notional_usd=v))
                self.assertNotEqual(d["decision"], "PERMIT")

    def test_control_a_real_number_under_the_cap_still_permits(self):
        self.assertEqual(
            decide.decide(POLICY, ["PASS"], ctx(notional_usd=100))["decision"],
            "PERMIT")

    def test_control_a_real_number_over_the_cap_still_blocks(self):
        self.assertEqual(
            decide.decide(POLICY, ["PASS"],
                          ctx(notional_usd=999999999))["decision"], "BLOCK")


class IdempotencyKeyIsBoundToItsRequest(unittest.TestCase):
    """A key names one request. Replaying it for another approves the unreviewed.

    The September fix closed the race, where two identical requests both
    executed. This is the collision: one key speaking for two different
    requests. A $100 order established a PERMIT and a $999,999,999 order with
    the same key inherited it, with reasons still reporting observed: 100.
    """

    BODY = {"idempotency_key": "k1",
            "action": {"type": "broker.order.create"},
            "outcomes": ["PASS"],
            "context": {"action": {"notional_usd": 100},
                        "evidence": {"quote": {"age_ms": 50,
                                               "deviation_bps": 1}},
                        "portfolio": {"daily_turnover_pct": 1}}}

    def setUp(self):
        import serve
        self.serve = serve
        self.g = serve.Gateway(POLICY, mode="enforce")

    def body(self, **over):
        b = json.loads(json.dumps(self.BODY))
        b.update(over)
        return b

    def test_control_an_identical_replay_returns_the_same_decision(self):
        first = self.g.decide_request(self.body())
        again = self.g.decide_request(self.body())
        self.assertEqual(first["decision"], "PERMIT")
        self.assertEqual(again["decision"], "PERMIT")
        self.assertEqual(first["receipt"], again["receipt"],
                         "idempotency must still return the SAME receipt")

    def test_a_different_context_under_the_same_key_is_refused(self):
        self.g.decide_request(self.body())
        evil = self.body()
        evil["context"]["action"]["notional_usd"] = 999999999
        with self.assertRaises(self.serve.BadRequest):
            self.g.decide_request(evil)

    def test_a_different_action_under_the_same_key_is_refused(self):
        self.g.decide_request(self.body())
        evil = self.body()
        evil["action"] = {"type": "broker.order.cancel"}
        with self.assertRaises(self.serve.BadRequest):
            self.g.decide_request(evil)

    def test_different_outcomes_under_the_same_key_are_refused(self):
        self.g.decide_request(self.body())
        evil = self.body()
        evil["outcomes"] = ["FAIL_UNSAFE"]
        with self.assertRaises(self.serve.BadRequest):
            self.g.decide_request(evil)

    def test_control_a_fresh_key_evaluates_the_big_order_on_its_merits(self):
        self.g.decide_request(self.body())
        fresh = self.body(idempotency_key="k2")
        fresh["context"]["action"]["notional_usd"] = 999999999
        self.assertEqual(self.g.decide_request(fresh)["decision"], "BLOCK")


if __name__ == "__main__":
    unittest.main()
