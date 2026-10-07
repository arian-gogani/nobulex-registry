"""Offline regression of the recipient expression actually written by run.py.

No subject process, dependency install, or network request is involved.
"""
import ast
from pathlib import Path
import runpy
from types import SimpleNamespace
import unittest


SOURCE = Path(__file__).with_name("run.py")
NAMESPACE = runpy.run_path(str(SOURCE), run_name="recipient_regression")
TREE = ast.parse(SOURCE.read_text())
EXPRESSIONS = [value for node in ast.walk(TREE) if isinstance(node, ast.Dict)
               for key, value in zip(node.keys, node.values)
               if isinstance(key, ast.Constant) and key.value == "recipient"]
assert len(EXPRESSIONS) == 1, "The record must have one recipient expression"
EXPRESSION = compile(ast.Expression(EXPRESSIONS[0]), str(SOURCE), "eval")


class RecipientTests(unittest.TestCase):
    def test_record_recipient_uses_subject_origin_not_upstream(self):
        for origin in ("https://github.com/pycodebr/yfinance-mcp-server.git",
                       "git@github.com:pycodebr/yfinance-mcp-server.git"):
            for upstream in ("Yahoo Finance", "A different vendor"):
                with self.subTest(origin=origin, upstream=upstream):
                    actual = eval(EXPRESSION, NAMESPACE, {
                        "origin": origin, "args": SimpleNamespace(upstream=upstream)})
                    self.assertEqual(actual, "maintainer of subject repository " + origin)

    def test_missing_origin_does_not_invent_a_recipient(self):
        for origin in (None, "", "   ", 123):
            with self.subTest(origin=origin):
                self.assertIsNone(eval(EXPRESSION, NAMESPACE, {
                    "origin": origin, "args": SimpleNamespace(upstream="Yahoo Finance")}))


if __name__ == "__main__":
    unittest.main()
