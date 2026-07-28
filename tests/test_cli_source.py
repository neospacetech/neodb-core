import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli.__main__ import main, run_repl, run_script
from cli.source import StatementBuffer, split_script
from engine import NeoDBEngine


class StatementBufferTests(unittest.TestCase):
    def test_buffers_delimiters_strings_and_trailing_chains(self):
        buffer = StatementBuffer()
        self.assertEqual(buffer.feed("create dataset users(table{"), [])
        self.assertTrue(buffer.pending)
        self.assertEqual(buffer.feed('name(str(20), default("}"))'), [])
        statements = buffer.feed("})")
        self.assertEqual(len(statements), 1)
        self.assertIn('default("}")', statements[0])
        self.assertFalse(buffer.pending)

        self.assertEqual(buffer.feed("users()."), [])
        self.assertEqual(buffer.feed("limit(1)"), ["users().\nlimit(1)"])

    def test_splits_comments_blank_lines_and_semicolons(self):
        statements = split_script(
            """
            # setup
            create dataset users(table{id(int)})

            add {id=1} into users; users()
            """
        )
        self.assertEqual(len(statements), 3)
        self.assertIn("create dataset users", statements[0].source)
        self.assertEqual(statements[1].source, "add {id=1} into users")
        self.assertEqual(statements[2].source, "users()")

    def test_unterminated_input_is_returned_for_diagnostics(self):
        buffer = StatementBuffer()
        self.assertEqual(buffer.feed('users({name="Alice'), [])
        self.assertEqual(buffer.finish(), ['users({name="Alice'])

    def test_multiline_algebra_operators_continue_the_statement(self):
        statements = split_script(
            """
            combined = adults +
                employees &
                contractors
            combined
            """
        )
        self.assertEqual(len(statements), 2)
        self.assertIn("adults +", statements[0].source)
        self.assertIn("employees &", statements[0].source)


class ReplBufferingTests(unittest.TestCase):
    def test_repl_uses_continuation_prompt(self):
        inputs = iter(
            [
                "create dataset users(table{",
                "id(int)",
                "})",
                "quit",
            ]
        )
        prompts = []

        def read(prompt):
            prompts.append(prompt)
            return next(inputs)

        with patch("builtins.input", side_effect=read), patch("builtins.print"):
            run_repl()
        self.assertEqual(prompts, ["neodb> ", "... ", "... ", "neodb> "])


class ScriptExecutionTests(unittest.TestCase):
    def write_script(self, source):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "program.neoql"
        path.write_text(source, encoding="utf-8")
        return path

    def test_script_executes_multiple_statements_with_one_engine(self):
        path = self.write_script(
            """
            # a multiline schema
            create dataset users(table{
                id(int, pk),
                name(str(20))
            })

            add {id=1, name="Alice"} into users
            users()
            """
        )
        engine = NeoDBEngine()
        with patch("builtins.print") as output:
            status = run_script(path, engine)
        self.assertEqual(status, 0)
        self.assertIn("users", engine.datasets)
        rendered = [call.args[0] for call in output.call_args_list]
        self.assertEqual(json.loads(rendered[-1]), [{"id": 1, "name": "Alice"}])

    def test_script_diagnostic_has_filename_and_global_location(self):
        path = self.write_script(
            "create dataset users(table{id(int)})\nusers({id ~~ 1})\n"
        )
        with patch("builtins.print") as output:
            status = run_script(path)
        self.assertEqual(status, 1)
        human = output.call_args_list[-2].args[0]
        payload = json.loads(output.call_args_list[-1].args[0])
        self.assertIn(f"{path}:2:", human)
        self.assertEqual(payload["filename"], str(path))
        self.assertEqual(payload["location"]["start"]["line"], 2)

    def test_missing_script_has_deterministic_exit_status(self):
        with patch("builtins.print"):
            self.assertEqual(run_script("/definitely/missing/program.neoql"), 2)

    def test_main_dispatches_to_script_mode(self):
        path = self.write_script("# empty script\n")
        self.assertEqual(main([str(path)]), 0)


if __name__ == "__main__":
    unittest.main()
