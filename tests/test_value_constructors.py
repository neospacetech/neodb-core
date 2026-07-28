import unittest
from datetime import date

from engine import NeoDBEngine
from neoql.ast import FunctionCallValue, SelectionValue, TypeValue
from neoql.errors import (
    FunctionArityError,
    FunctionTypeError,
    NeoQLSyntaxError,
    ReferenceConflictError,
)
from neoql.parser import parse_statement, statement_to_query
from neoql.references import ReferenceValue
from neoql.runtime import NeoQLSession
from neoql.types import NeoQLTypeError


class ValueConstructorParserTests(unittest.TestCase):
    def test_cast_keeps_a_source_located_type_expression(self):
        statement = parse_statement(
            'add {id=cast("7", int), values=cast(["1"], list(int))} into rows'
        )
        first = statement.records[0].fields[0].value
        self.assertIsInstance(first, FunctionCallValue)
        assert isinstance(first, FunctionCallValue)
        self.assertEqual(first.name, "cast")
        self.assertIsInstance(first.arguments[1], TypeValue)
        target = first.arguments[1]
        assert isinstance(target, TypeValue)
        self.assertEqual(target.type_ref.name, "int")
        self.assertEqual(target.span.start.column, 19)

        nested = statement.records[0].fields[1].value
        assert isinstance(nested, FunctionCallValue)
        nested_target = nested.arguments[1]
        assert isinstance(nested_target, TypeValue)
        self.assertEqual(nested_target.type_ref.render(), "list(int)")

    def test_collection_constructor_accepts_selection_values(self):
        statement = parse_statement(
            "add {id=1, members=set(users({id=1}), users({id=2}))} into teams"
        )
        constructor = statement.records[0].fields[1].value
        self.assertIsInstance(constructor, FunctionCallValue)
        assert isinstance(constructor, FunctionCallValue)
        self.assertEqual(constructor.name, "set")
        self.assertTrue(
            all(isinstance(value, SelectionValue) for value in constructor.arguments)
        )

    def test_direct_adapter_requires_a_session_for_value_calls(self):
        statement = parse_statement('add {id=cast("1", int)} into rows')
        with self.assertRaisesRegex(
            NeoQLSyntaxError,
            "Scalar function values require a NeoQL session",
        ):
            statement_to_query(statement)


class ValueConstructorRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.engine = NeoDBEngine()
        self.session = NeoQLSession(self.engine)

    def test_list_set_tuple_and_map_have_defined_collection_semantics(self):
        self.assertEqual(self.session.execute("list(1, 2, 2)"), [1, 2, 2])
        self.assertEqual(self.session.execute("set(1, 2, 2)"), {1, 2})
        self.assertEqual(self.session.execute('tuple(1, "a", null)'), (1, "a", None))
        self.assertEqual(
            self.session.execute('map({first=1, second=list(2, 3), first="last"})'),
            {"first": "last", "second": [2, 3]},
        )
        self.assertEqual(self.session.execute("list()"), [])
        self.assertEqual(self.session.execute("set()"), set())
        self.assertEqual(self.session.execute("tuple()"), ())
        self.assertEqual(self.session.execute("list(null)"), [None])
        self.assertEqual(self.session.execute("set(null)"), {None})

    def test_explicit_cast_reuses_all_existing_type_descriptors(self):
        self.assertEqual(self.session.execute('cast("7", int)'), 7)
        self.assertEqual(
            self.session.execute('cast(["1", "2"], list(int))'),
            [1, 2],
        )
        self.assertEqual(
            self.session.execute('cast(["1", "1"], set(int))'),
            {1},
        )
        self.assertEqual(
            self.session.execute('cast({first="1", second="2"}, map(str(10), int))'),
            {"first": 1, "second": 2},
        )
        self.assertEqual(
            self.session.execute('cast(["1", "true"], tuple(int, bool))'),
            (1, True),
        )
        self.assertEqual(
            self.session.execute('cast("2026-01-02", date)'),
            date(2026, 1, 2),
        )
        self.assertIsNone(self.session.execute("cast(null, nullable(int))"))

    def test_calls_work_in_defaults_records_predicates_methods_and_functions(self):
        self.session.execute(
            "create dataset rows("
            'table{id(int, pk), size(int, default(cast("2", int)))}'
            ")"
        )
        self.session.execute('add {id=cast("1", int)} into rows')
        self.session.execute("function pair(first, second){ tuple(first, second) }")

        self.assertEqual(self.engine.datasets["rows"].rows[0]["size"], 2)
        self.assertEqual(
            self.session.execute('rows({id=cast("1", int)})').consume(),
            [{"id": 1, "size": 2}],
        )
        self.assertEqual(
            self.session.execute("rows().limit(cast(1, int))").consume(),
            [{"id": 1, "size": 2}],
        )
        self.assertEqual(self.session.execute('pair(1, "two")'), (1, "two"))

    def test_selection_operands_expand_at_typed_reference_boundary(self):
        self.session.execute("create dataset users(table{id(int, pk), name(str(20))})")
        self.session.execute('add {id=1, name="A"}, {id=2, name="B"} into users')
        self.session.execute(
            "create dataset teams(table{id(int, pk), members(set(users))})"
        )
        self.session.execute(
            "add {id=1, members=set(users({id=1}), users({id=2}))} into teams"
        )
        self.session.execute("add {id=2, members=set(users())} into teams")

        expected = {
            ReferenceValue("users", (("id", 1),)),
            ReferenceValue("users", (("id", 2),)),
        }
        self.assertEqual(self.engine.datasets["teams"].rows[0]["members"], expected)
        self.assertEqual(self.engine.datasets["teams"].rows[1]["members"], expected)

        self.session.execute("create dataset groups(table{id(int, pk)})")
        self.session.execute("add {id=1} into groups")
        with self.assertRaises(ReferenceConflictError):
            self.session.execute("add {id=3, members=set(groups({id=1}))} into teams")

    def test_name_precedence_keeps_dataset_and_user_bindings(self):
        self.session.execute("create dataset list(table{id(int, pk)})")
        self.session.execute("add {id=1} into list")
        self.assertEqual(self.session.execute("list()").consume(), [{"id": 1}])

        self.session.execute("function set(value){ value }")
        self.assertEqual(self.session.execute("set(7)"), 7)
        self.assertEqual(self.session.execute("tuple(7)"), (7,))

    def test_invalid_values_have_source_located_stable_diagnostics(self):
        with self.assertRaises(NeoQLTypeError) as cast_error:
            self.session.execute('\ncast("not-an-int", int)')
        self.assertEqual(cast_error.exception.code, "type_mismatch")
        self.assertEqual(cast_error.exception.span.start.line, 2)

        with self.assertRaises(FunctionArityError) as arity:
            self.session.execute("cast(1, int, 2)")
        self.assertEqual(arity.exception.details["expected"], 2)
        self.assertEqual(arity.exception.details["actual"], 3)

        with self.assertRaises(FunctionTypeError) as mapping:
            self.session.execute("map(1)")
        self.assertEqual(mapping.exception.details["expected"], "object")

        with self.assertRaises(FunctionTypeError) as hashing:
            self.session.execute("set(1, [2])")
        self.assertEqual(hashing.exception.details["position"], 2)

        with self.assertRaises(NeoQLTypeError):
            self.session.execute('cast("x", list)')


if __name__ == "__main__":
    unittest.main()
