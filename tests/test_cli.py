import unittest
from unittest.mock import patch

from cli.__main__ import (
    execute_cli_command,
    main,
    parse_cli_command,
    parse_filters,
    parse_objects_list,
    run,
    show_help,
)
from engine import NeoDBEngine


class CLIErrorTests(unittest.TestCase):
    def test_invalid_commands_are_rejected(self):
        invalid_commands = [
            "create dataset",
            "add nope into users",
            "users({age ~~ 2})",
            "users().unknown(value)",
        ]
        for command in invalid_commands:
            with self.subTest(command=command), self.assertRaises(ValueError):
                parse_cli_command(command)

    def test_invalid_record_and_predicate_are_rejected(self):
        with self.assertRaises(ValueError):
            parse_objects_list("not-a-record")
        with self.assertRaises(ValueError):
            parse_filters("{not a predicate}")

    def test_help_output(self):
        with patch("builtins.print") as output:
            show_help("create")
            show_help("missing")
        self.assertIn("create dataset", output.call_args_list[0].args[0])
        self.assertIn("No help available", output.call_args_list[1].args[0])

    def test_run_reports_engine_errors(self):
        with patch("builtins.print") as output:
            result = run(
                NeoDBEngine(),
                {"action": "select", "dataset": "missing"},
            )
        self.assertIsNone(result)
        self.assertIn("not found", output.call_args_list[-1].args[0])


class TransactionShellTests(unittest.TestCase):
    def setUp(self):
        self.engine = NeoDBEngine()

    @patch("builtins.print")
    def test_commit_publishes_engine_transaction(self, _output):
        transaction_id = execute_cli_command(self.engine, "begin")
        self.assertEqual(self.engine.active_transaction_id, transaction_id)
        self.assertEqual(
            execute_cli_command(
                self.engine,
                "create dataset users(table{id(int, pk)})",
            ),
            {"status": "success", "dataset": "users"},
        )
        self.assertEqual(execute_cli_command(self.engine, "commit"), transaction_id)
        self.assertEqual(self.engine.transaction_depth, 0)
        self.assertIn("users", self.engine.datasets)

    @patch("builtins.print")
    def test_abort_discards_engine_transaction(self, _output):
        transaction_id = execute_cli_command(self.engine, "start transaction")
        execute_cli_command(
            self.engine,
            "create dataset temporary(table{id(int)})",
        )
        self.assertEqual(
            execute_cli_command(self.engine, "abort transaction"),
            transaction_id,
        )
        self.assertNotIn("temporary", self.engine.datasets)

    @patch("builtins.print")
    def test_shell_exits_on_quit_or_eof(self, _output):
        with patch("builtins.input", return_value="quit"):
            main([])
        with patch("builtins.input", side_effect=EOFError):
            main([])


if __name__ == "__main__":
    unittest.main()
