import json
import unittest
from unittest.mock import patch

from cli.__main__ import execute_cli_command, parse_cli_command, run
from engine import NeoDBEngine
from neoql import (
    DatasetNotFoundError,
    DeadlockError,
    DiagnosticError,
    InvalidTraversalError,
    MissingReferenceError,
    PermissionDeniedError,
    QueryTimeoutError,
    UnknownFieldError,
)
from neoql.errors import NeoQLSyntaxError
from neoql.schema import ConstraintViolation, SchemaDefinitionError
from neoql.types import NeoQLTypeError


class PublicDiagnosticTests(unittest.TestCase):
    def test_runtime_taxonomy_has_stable_payloads(self):
        errors: list[tuple[DiagnosticError, str]] = [
            (DatasetNotFoundError("users"), "unknown_dataset"),
            (UnknownFieldError("users", "missing"), "unknown_field"),
            (InvalidTraversalError("Cannot traverse scalar"), "invalid_traversal"),
            (MissingReferenceError("users", 42), "missing_reference"),
            (QueryTimeoutError(100), "timeout"),
            (DeadlockError("tx-1"), "deadlock"),
            (PermissionDeniedError("delete", "users"), "permission_denied"),
        ]
        for error, code in errors:
            with self.subTest(code=code):
                payload = error.to_dict()
                self.assertEqual(payload["code"], code)
                self.assertIn(payload["phase"], {"compile", "plan", "runtime"})
                self.assertIsInstance(payload["details"], dict)

    def test_specialized_errors_share_the_public_contract(self):
        errors = [
            NeoQLTypeError("bad type"),
            SchemaDefinitionError("bad schema", field="id"),
            ConstraintViolation(
                "unique",
                "duplicate",
                dataset="users",
                field="email",
            ),
        ]
        for error in errors:
            with self.subTest(error=type(error).__name__):
                self.assertIsInstance(error, DiagnosticError)
                self.assertEqual(error.to_dict()["message"], error.message)

    def test_compile_time_errors_include_source_locations(self):
        cases = [
            "users({",
            "create dataset users(table{id(list)})",
            "create dataset users(table{id(int, nullable, pk)})",
        ]
        for source in cases:
            with (
                self.subTest(source=source),
                self.assertRaises(DiagnosticError) as raised,
            ):
                parse_cli_command(source)
            location = raised.exception.to_dict()["location"]
            self.assertGreaterEqual(location["start"]["line"], 1)
            self.assertGreaterEqual(location["start"]["column"], 1)

    def test_syntax_diagnostic_keeps_human_readable_caret(self):
        with self.assertRaises(NeoQLSyntaxError) as raised:
            parse_cli_command("users({age ~~ 2})")
        self.assertIn("^", str(raised.exception))
        self.assertEqual(raised.exception.to_dict()["phase"], "parse")

    def test_table_projection_and_order_reject_unknown_fields(self):
        engine = NeoDBEngine()
        engine.create_dataset("users", "table", {"id": {"type": "int"}})
        queries = [
            {
                "action": "select",
                "dataset": "users",
                "select": ["missing"],
            },
            {
                "action": "select",
                "dataset": "users",
                "order_by": [{"field": "missing", "direction": "asc"}],
            },
        ]
        for query in queries:
            with (
                self.subTest(query=query),
                self.assertRaises(UnknownFieldError) as raised,
            ):
                engine.execute_query(query)
            self.assertEqual(raised.exception.code, "unknown_field")


class CLIDiagnosticTests(unittest.TestCase):
    def test_cli_is_concise_and_machine_readable(self):
        with patch("builtins.print") as output:
            result = run(
                NeoDBEngine(),
                {"action": "select", "dataset": "missing"},
            )
        self.assertIsNone(result)
        human = output.call_args_list[-2].args[0]
        machine = json.loads(output.call_args_list[-1].args[0])
        self.assertEqual(human, "Error [unknown_dataset]: Dataset 'missing' not found")
        self.assertEqual(machine["code"], "unknown_dataset")
        self.assertEqual(machine["details"]["dataset"], "missing")

    def test_cli_renders_compile_time_diagnostics_without_exiting(self):
        with patch("builtins.print") as output:
            result = execute_cli_command(NeoDBEngine(), "users({")
        self.assertIsNone(result)
        machine = json.loads(output.call_args_list[-1].args[0])
        self.assertEqual(machine["code"], "syntax_error")
        self.assertIn("location", machine)


if __name__ == "__main__":
    unittest.main()
