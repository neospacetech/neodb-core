import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli.__main__ import run_script
from engine import NeoDBEngine
from neoql.ast import (
    FunctionCallStatement,
    FunctionDeclarationStatement,
    ParameterReference,
    VariableAssignmentStatement,
)
from neoql.errors import (
    FunctionArityError,
    ImmutableBindingError,
    RecursionNotAllowedError,
    UnknownFunctionError,
    UnknownNameError,
)
from neoql.parser import parse_statement
from neoql.runtime import NeoQLSession
from neoql.selection import Selection


class LanguageParserTests(unittest.TestCase):
    def test_assignment_and_function_nodes_keep_source_locations(self):
        assignment = parse_statement("adults = users({age>=18})")
        self.assertIsInstance(assignment, VariableAssignmentStatement)
        assert isinstance(assignment, VariableAssignmentStatement)
        self.assertEqual(assignment.name, "adults")
        self.assertEqual(assignment.span.start.column, 1)
        self.assertEqual(assignment.expression.span.start.column, 10)

        declaration = parse_statement("function byAge(age){\n  users({age>=age})\n}")
        self.assertIsInstance(declaration, FunctionDeclarationStatement)
        assert isinstance(declaration, FunctionDeclarationStatement)
        self.assertEqual(declaration.parameters, ("age",))
        predicate = declaration.body.predicate
        assert predicate is not None
        self.assertIsInstance(predicate.value, ParameterReference)
        self.assertEqual(predicate.value.span.start.line, 2)

    def test_scalar_invocation_parses_as_function_call(self):
        call = parse_statement('byRole("Engineer")')
        self.assertIsInstance(call, FunctionCallStatement)
        assert isinstance(call, FunctionCallStatement)
        self.assertEqual(call.name, "byRole")
        self.assertEqual(call.arguments[0].value, "Engineer")


class SessionRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.engine = NeoDBEngine()
        self.session = NeoQLSession(self.engine)
        self.session.execute(
            "create dataset users(table{id(int, pk), age(int), role(str(20))})"
        )
        self.session.execute(
            'add {id=1, age=20, role="Engineer"}, '
            '{id=2, age=12, role="Student"} into users'
        )

    def test_assignment_is_immutable_and_remains_lazy(self):
        dataset = self.engine.datasets["users"]
        with patch.object(
            dataset,
            "_selection_records",
            wraps=dataset._selection_records,
        ) as scan:
            result = self.session.execute("adults = users({age>=18})")
            self.assertEqual(result, {"status": "bound", "name": "adults"})
            scan.assert_not_called()

            selection = self.session.execute("adults")
            self.assertIsInstance(selection, Selection)
            self.assertEqual(
                selection.consume(), [{"id": 1, "age": 20, "role": "Engineer"}]
            )
            scan.assert_called_once()

        with self.assertRaises(ImmutableBindingError) as raised:
            self.session.execute("adults = users()")
        self.assertEqual(raised.exception.code, "immutable_binding")
        self.assertEqual(raised.exception.span.start.column, 1)

    def test_variable_can_be_refined_without_changing_its_plan(self):
        self.session.execute("allUsers = users()")
        original = self.session.execute("allUsers")
        refined = self.session.execute("allUsers().limit(1)")
        self.assertEqual(len(original.plan), 0)
        self.assertEqual(len(refined.plan), 1)
        self.assertEqual([row["id"] for row in refined.consume()], [1])

    def test_functions_bind_arguments_return_lazily_and_use_lexical_parameters(self):
        self.session.execute("function byAge(minimum){ users({age>=minimum}) }")
        self.session.execute("function identity(value){ value }")
        result = self.session.execute("byAge(18)")
        self.assertIsInstance(result, Selection)
        self.assertEqual([row["id"] for row in result.consume()], [1])
        self.assertEqual(self.session.execute('identity("local")'), "local")

        with self.assertRaises(UnknownNameError):
            self.session.execute("minimum")

    def test_one_namespace_prevents_dataset_and_binding_shadowing(self):
        self.session.execute("function reports(){ users() }")
        with self.assertRaises(ImmutableBindingError):
            self.session.execute("create dataset reports(table{id(int)})")

    def test_functions_can_call_functions_and_global_selections(self):
        self.session.execute("adults = users({age>=18})")
        self.session.execute("function firstAdult(){ adults().limit(1) }")
        self.session.execute("function first(count){ users().limit(count) }")
        self.session.execute("function byAge(minimum){ users({age>=minimum}) }")
        self.session.execute("function delegated(minimum){ byAge(minimum) }")
        self.assertEqual(
            [row["id"] for row in self.session.execute("firstAdult()").consume()],
            [1],
        )
        self.assertEqual(
            [row["id"] for row in self.session.execute("first(1)").consume()],
            [1],
        )
        self.assertEqual(
            [row["id"] for row in self.session.execute("delegated(18)").consume()],
            [1],
        )

    def test_function_diagnostics_cover_unknown_arity_and_recursion(self):
        with self.assertRaises(UnknownFunctionError) as unknown:
            self.session.execute("missing(1)")
        self.assertEqual(unknown.exception.code, "unknown_function")

        self.session.execute("function byAge(minimum){ users({age>=minimum}) }")
        with self.assertRaises(FunctionArityError) as arity:
            self.session.execute("byAge()")
        self.assertEqual(arity.exception.details["expected"], 1)

        self.session.execute("function loop(){ loop() }")
        with self.assertRaises(RecursionNotAllowedError) as recursion:
            self.session.execute("loop()")
        self.assertEqual(recursion.exception.code, "recursion_not_allowed")

    def test_unknown_variable_has_source_location(self):
        with self.assertRaises(UnknownNameError) as raised:
            self.session.execute("\nmissing")
        self.assertEqual(raised.exception.span.start.line, 2)
        self.assertIn("line 2, column 1", str(raised.exception))


class ScriptLanguageTests(unittest.TestCase):
    def test_script_shares_bindings_and_functions_across_statements(self):
        source = """
create dataset users(table{id(int, pk), age(int)})
add {id=1, age=20}, {id=2, age=12} into users
adults = users({age>=18})
function firstAdult(){ adults().limit(1) }
firstAdult()
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "program.neoql"
            path.write_text(source, encoding="utf-8")
            with patch("builtins.print") as output:
                status = run_script(path)
        self.assertEqual(status, 0)
        rendered = [call.args[0] for call in output.call_args_list]
        self.assertEqual(json.loads(rendered[-1]), [{"age": 20, "id": 1}])


if __name__ == "__main__":
    unittest.main()
