import unittest

from cli.__main__ import parse_cli_command
from datasets.table import TableDataset
from neoql.predicates import (
    PredicateEvaluationError,
    evaluate_operator,
    evaluate_predicate,
    validate_predicate,
)
from neoql.schema import DatasetSchema


class BooleanTruthTableTests(unittest.TestCase):
    def test_and_or_and_not_truth_tables(self):
        for left in (False, True):
            for right in (False, True):
                record = {"left": left, "right": right}
                left_predicate = {
                    "field": "left",
                    "op": "=",
                    "value": True,
                }
                right_predicate = {
                    "field": "right",
                    "op": "=",
                    "value": True,
                }
                with self.subTest(left=left, right=right):
                    self.assertEqual(
                        evaluate_predicate(
                            record,
                            {"and": [left_predicate, right_predicate]},
                        ),
                        left and right,
                    )
                    self.assertEqual(
                        evaluate_predicate(
                            record,
                            {"or": [left_predicate, right_predicate]},
                        ),
                        left or right,
                    )
                    self.assertEqual(
                        evaluate_predicate(record, {"not": left_predicate}),
                        not left,
                    )

    def test_parser_precedence_and_parentheses(self):
        ordinary = parse_cli_command("flags({a=true || b=true && c=true})")["filter"]
        grouped = parse_cli_command("flags({(a=true || b=true) && c=true})")["filter"]
        record = {"a": True, "b": False, "c": False}
        self.assertTrue(evaluate_predicate(record, ordinary))
        self.assertFalse(evaluate_predicate(record, grouped))


class OperatorSemanticsTests(unittest.TestCase):
    def test_comparison_operators(self):
        cases = [
            (1, "=", 1, True),
            (1, "!=", 2, True),
            (2, ">", 1, True),
            (2, ">=", 2.0, True),
            (1, "<", 2, True),
            (1, "<=", 1.0, True),
        ]
        for actual, operator, expected, result in cases:
            with self.subTest(operator=operator):
                self.assertEqual(
                    evaluate_operator(actual, operator, expected),
                    result,
                )

    def test_membership_and_string_operators(self):
        cases = [
            ("admin", "in", ["admin", "author"], True),
            ("missing", "in", ["admin"], False),
            (["admin", "author"], "contains", "author", True),
            ({"admin": True}, "contains", "admin", True),
            ("Alice", "contains", "lic", True),
            ("Alice", "startsWith", "Al", True),
            ("Alice", "endsWith", "ice", True),
            ("Alice", "matches", r"^A.*e$", True),
        ]
        for actual, operator, expected, result in cases:
            with self.subTest(operator=operator):
                self.assertEqual(
                    evaluate_operator(actual, operator, expected),
                    result,
                )

    def test_null_semantics(self):
        self.assertTrue(evaluate_operator(None, "=", None))
        self.assertFalse(evaluate_operator(None, "!=", None))
        self.assertTrue(evaluate_operator(None, "!=", 1))
        self.assertFalse(evaluate_operator(None, ">", 1))
        self.assertFalse(evaluate_operator(None, "contains", "x"))
        self.assertTrue(evaluate_operator(None, "in", [None, 1]))

    def test_incompatible_and_invalid_operands_are_structured(self):
        cases = [
            (1, "=", "1", "type_mismatch"),
            (1, "contains", 1, "invalid_operand"),
            (1, "in", 1, "invalid_operand"),
            ("value", "startsWith", 1, "type_mismatch"),
            ("value", "matches", "[", "invalid_pattern"),
            (1, "unknown", 1, "unknown_operator"),
        ]
        for actual, operator, expected, code in cases:
            with (
                self.subTest(operator=operator),
                self.assertRaises(PredicateEvaluationError) as raised,
            ):
                evaluate_operator(actual, operator, expected, field="field")
            self.assertEqual(raised.exception.code, code)
            self.assertEqual(raised.exception.to_dict()["error"], "predicate")


class PredicateValidationTests(unittest.TestCase):
    def setUp(self):
        self.schema = DatasetSchema.from_mapping(
            "users",
            {
                "age": {"type": "int"},
                "name": {"type": "str(100)"},
                "tags": {"type": "list(str(20))"},
                "settings": {"type": "map(str(20), json)"},
                "optional": {"type": "nullable(int)"},
            },
        )

    def test_schema_validation_accepts_compatible_predicates(self):
        valid = [
            {"field": "age", "op": ">=", "value": 18},
            {"field": "age", "op": "in", "value": [18, 21]},
            {"field": "name", "op": "startsWith", "value": "A"},
            {"field": "tags", "op": "contains", "value": "admin"},
            {"field": "settings", "op": "contains", "value": "theme"},
            {"field": "optional", "op": "=", "value": None},
        ]
        for predicate in valid:
            with self.subTest(predicate=predicate):
                validate_predicate(predicate, self.schema)

    def test_schema_validation_rejects_errors_without_records(self):
        invalid = [
            (
                {"field": "missing", "op": "=", "value": 1},
                "unknown_field",
            ),
            (
                {"field": "age", "op": "=", "value": "18"},
                "type_mismatch",
            ),
            (
                {"field": "age", "op": "startsWith", "value": "1"},
                "type_mismatch",
            ),
            (
                {"field": "tags", "op": ">", "value": ["a"]},
                "invalid_operand",
            ),
            (
                {"field": "age", "op": "in", "value": 18},
                "invalid_operand",
            ),
            (
                {"field": "age", "op": "in", "value": None},
                "invalid_operand",
            ),
            (
                {"field": "name", "op": "startsWith", "value": None},
                "type_mismatch",
            ),
            (
                {"field": "tags", "op": "=", "value": [1]},
                "type_mismatch",
            ),
        ]
        for predicate, code in invalid:
            with (
                self.subTest(predicate=predicate),
                self.assertRaises(PredicateEvaluationError) as raised,
            ):
                validate_predicate(predicate, self.schema)
            self.assertEqual(raised.exception.code, code)

    def test_table_validates_predicates_even_when_empty(self):
        table = TableDataset("users", {"age": {"type": "int"}})
        with self.assertRaisesRegex(PredicateEvaluationError, "incompatible"):
            table.query(
                {
                    "action": "select",
                    "filter": {
                        "field": "age",
                        "op": "=",
                        "value": "old",
                    },
                }
            )

    def test_malformed_predicate_shapes_are_rejected(self):
        malformed = [
            {"and": []},
            {"or": "not-a-list"},
            {"not": "not-a-predicate"},
            {"field": 1, "op": "="},
        ]
        for predicate in malformed:
            with (
                self.subTest(predicate=predicate),
                self.assertRaises(PredicateEvaluationError),
            ):
                evaluate_predicate({}, predicate)


if __name__ == "__main__":
    unittest.main()
