import unittest
from unittest.mock import patch

from cli.__main__ import parse_cli_command
from cli.source import split_script
from engine import NeoDBEngine
from neoql.ast import DatasetOptions, SelectionStatement
from neoql.errors import NeoQLSyntaxError, UnknownFieldError
from neoql.parser import parse_statement, statement_to_query
from neoql.runtime import NeoQLSession


class DatasetOptionsParserTests(unittest.TestCase):
    def test_named_and_predicated_options_have_source_located_ast(self):
        named = parse_statement(
            "users(options={select=[id, name], order=[name, desc], limit=2})"
        )
        self.assertIsInstance(named, SelectionStatement)
        assert isinstance(named, SelectionStatement)
        self.assertIsNone(named.predicate)
        self.assertIsInstance(named.options, DatasetOptions)
        assert named.options is not None
        self.assertEqual(
            [field.name for field in named.options.fields],
            ["select", "order", "limit"],
        )
        self.assertEqual(named.options.span.start.column, 15)

        predicated = parse_statement(
            "users({active=true}, options={offset=1, limit=2})"
        )
        assert isinstance(predicated, SelectionStatement)
        self.assertIsNotNone(predicated.predicate)
        self.assertIsNotNone(predicated.options)
        assert predicated.options is not None
        self.assertEqual(predicated.options.span.start.column, 30)

        bare = parse_statement("users({active=true}, {limit=2})")
        assert isinstance(bare, SelectionStatement)
        self.assertIsNotNone(bare.options)

    def test_options_compile_to_canonical_ordered_plan_nodes(self):
        query = statement_to_query(
            parse_statement(
                "users({active=true}, "
                "{limit=2, order=[age, desc], offset=1, select=[id, age]})"
            )
        )
        self.assertEqual(
            query["pipeline"],
            [
                {"operation": "project", "fields": ["id", "age"]},
                {"operation": "order", "field": "age", "direction": "desc"},
                {"operation": "offset", "count": 1},
                {"operation": "limit", "count": 2},
            ],
        )

    def test_cli_and_script_buffer_accept_option_forms(self):
        query = parse_cli_command("users(options={limit=2})")
        self.assertEqual(query["pipeline"], [{"operation": "limit", "count": 2}])
        statements = split_script(
            """
            users(options={
                order=[age, desc],
                limit=2
            })
            users({active=true}, {offset=1})
            """
        )
        self.assertEqual(len(statements), 2)
        self.assertTrue(
            all(
                statement_to_query(parse_statement(statement.source))["pipeline"]
                for statement in statements
            )
        )

    def test_unknown_duplicate_and_invalid_options_are_source_located(self):
        invalid = (
            ("users(options={missing=1})", "Unknown dataset option"),
            ("users(options={limit=1, limit=2})", "Duplicate dataset option"),
            ("users(options={select=[]})", "non-empty field list"),
            ("users(options={select=[id, 2]})", "non-empty field list"),
            ("users(options={order=[]})", r"expects \[field\]"),
            ("users(options={order=[age, sideways]})", r"expects \[field\]"),
            ("users(options={offset=-1})", "non-negative integer"),
            ("users(options={limit=true})", "non-negative integer"),
        )
        for source, message in invalid:
            with (
                self.subTest(source=source),
                self.assertRaisesRegex(NeoQLSyntaxError, message) as raised,
            ):
                statement_to_query(parse_statement(source))
            self.assertIsNotNone(raised.exception.span)


class DatasetOptionsRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.engine = NeoDBEngine()
        self.session = NeoQLSession(self.engine)
        self.session.execute(
            "create dataset users("
            "table{id(int, pk), age(int), name(str(20)), active(bool)}"
            ")"
        )
        self.session.execute(
            'add {id=1, age=30, name="A", active=true}, '
            '{id=2, age=40, name="B", active=false}, '
            '{id=3, age=20, name="C", active=true}, '
            '{id=4, age=10, name="D", active=true} into users'
        )

    def test_options_are_equivalent_to_chained_selection_methods(self):
        options = self.session.execute(
            "users({active=true}, "
            "{select=[id, age], order=[age, desc], offset=1, limit=2})"
        )
        chained = self.session.execute(
            "users({active=true}).(id, age).order(age desc).offset(1).limit(2)"
        )
        self.assertEqual(options.consume(), chained.consume())
        self.assertEqual(
            options.consume(),
            [{"id": 3, "age": 20}, {"id": 4, "age": 10}],
        )

    def test_options_precede_and_compose_with_chained_methods(self):
        result = self.session.execute(
            "users(options={order=[age, desc], offset=1}).offset(1).limit(1)"
        )
        self.assertEqual([row["id"] for row in result.consume()], [3])
        self.assertEqual(
            [node["node"] for node in result.explain()["logical"]],
            ["OrderPlan", "OffsetPlan", "OffsetPlan", "LimitPlan"],
        )

    def test_dynamic_option_values_use_the_session_scalar_resolver(self):
        result = self.session.execute(
            'users(options={offset=cast("1", int), limit=len([1, 2])})'
        )
        self.assertEqual([row["id"] for row in result.consume()], [2, 3])

    def test_options_remain_lazy_until_consumption(self):
        dataset = self.engine.datasets["users"]
        with patch.object(
            dataset,
            "_selection_records",
            wraps=dataset._selection_records,
        ) as scan:
            selection = self.session.execute(
                "users(options={order=[age, desc], limit=1})"
            )
            scan.assert_not_called()
            self.assertEqual([row["id"] for row in selection.consume()], [2])
            scan.assert_called_once()

    def test_option_fields_use_normal_dataset_validation(self):
        with self.assertRaises(UnknownFieldError):
            self.session.execute("users(options={select=[missing]})").consume()
        with self.assertRaises(UnknownFieldError):
            self.session.execute("users(options={order=[missing]})").consume()


if __name__ == "__main__":
    unittest.main()
