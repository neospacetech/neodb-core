import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from engine import NeoDBEngine
from neoql.ast import FunctionCallValue
from neoql.builtins import BUILTIN_NAMES, call_builtin, default_builtin_context
from neoql.errors import FunctionArityError, FunctionTypeError
from neoql.parser import parse_statement
from neoql.runtime import NeoQLSession
from neoql.selection import Selection


class BuiltinParserTests(unittest.TestCase):
    def test_registry_contains_the_v01_scalar_contract(self):
        self.assertEqual(
            BUILTIN_NAMES,
            {
                "len",
                "abs",
                "round",
                "lower",
                "upper",
                "contains",
                "today",
                "now",
                "uuid",
            },
        )

    def test_nested_scalar_call_is_a_source_located_record_value(self):
        statement = parse_statement('add {id=1, name=upper(lower("Alice"))} into users')
        value = statement.records[0].fields[1].value
        self.assertIsInstance(value, FunctionCallValue)
        assert isinstance(value, FunctionCallValue)
        self.assertEqual(value.name, "upper")
        self.assertIsInstance(value.arguments[0], FunctionCallValue)
        self.assertEqual(value.span.start.column, 17)


class BuiltinRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.instant = datetime(2025, 3, 4, 5, 6, 7, tzinfo=timezone.utc)
        self.identifier = UUID("12345678-1234-5678-1234-567812345678")
        self.engine = NeoDBEngine()
        self.session = NeoQLSession(
            self.engine,
            clock=lambda: self.instant,
            uuid_source=lambda: self.identifier,
        )

    def test_scalar_builtins_define_values_and_return_types(self):
        cases = {
            'len("NeoDB")': 5,
            "len([1, 2, 3])": 3,
            "abs(-4)": 4,
            "round(3.14159, 2)": 3.14,
            'lower("ALICE")': "alice",
            'upper("alice")': "ALICE",
            'contains("NeoDB", "DB")': True,
            "contains([1, 2], 3)": False,
            "today()": date(2025, 3, 4),
            "now()": self.instant,
            "uuid()": self.identifier,
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(self.session.execute(source), expected)

        rounded = self.session.execute("round(2.5)")
        self.assertIsInstance(rounded, int)
        decimal = call_builtin(
            "abs",
            [Decimal("-1.25")],
            default_builtin_context(),
        )
        self.assertEqual(decimal, Decimal("1.25"))

    def test_null_propagates_without_coercion(self):
        for source in (
            "len(null)",
            "abs(null)",
            "round(null)",
            "round(1.2, null)",
            "lower(null)",
            "upper(null)",
            'contains(null, "x")',
            'contains("x", null)',
        ):
            with self.subTest(source=source):
                self.assertIsNone(self.session.execute(source))

    def test_arity_and_type_errors_are_stable_and_source_located(self):
        with self.assertRaises(FunctionArityError) as arity:
            self.session.execute("\nround()")
        self.assertEqual(arity.exception.code, "function_arity")
        self.assertEqual(arity.exception.details["expected"], "1 or 2")
        self.assertEqual(arity.exception.span.start.line, 2)

        with self.assertRaises(FunctionTypeError) as value_type:
            self.session.execute('contains("abc", 1)')
        self.assertEqual(value_type.exception.code, "function_type")
        self.assertEqual(value_type.exception.category, "type")
        self.assertEqual(value_type.exception.details["position"], 2)
        self.assertEqual(value_type.exception.span.start.column, 1)

        with self.assertRaises(FunctionTypeError):
            self.session.execute("abs(true)")
        with self.assertRaises(FunctionTypeError):
            self.session.execute('round(1.2, "two")')
        with self.assertRaises(FunctionTypeError):
            self.session.execute("len(1)")

    def test_calls_work_in_functions_records_predicates_and_methods(self):
        self.session.execute("function normalize(value){ lower(value) }")
        self.assertEqual(self.session.execute('normalize("ALICE")'), "alice")
        self.assertEqual(self.session.execute('upper(normalize("alice"))'), "ALICE")

        self.session.execute(
            "create dataset valueset("
            "table{id(int, pk), name(str(20)), size(int), created(date), "
            "stamp(datetime), token(uuid)}"
            ")"
        )
        self.session.execute(
            'add {id=1, name=normalize("ALICE"), size=len([1, 2]), '
            "created=today(), stamp=now(), token=uuid()} into valueset"
        )
        selected = self.session.execute(
            'valueset({name=lower("ALICE")}).limit(len([1]))'
        )
        self.assertEqual(len(selected.consume()), 1)
        row = self.engine.datasets["valueset"].rows[0]
        self.assertEqual(row["created"], date(2025, 3, 4))
        self.assertEqual(row["stamp"], self.instant)
        self.assertEqual(row["token"], self.identifier)

    def test_dataset_then_user_function_then_builtin_precedence(self):
        self.session.execute("create dataset uuid(table{id(int, pk)})")
        self.session.execute("add {id=1} into uuid")
        result = self.session.execute("uuid()")
        self.assertIsInstance(result, Selection)
        self.assertEqual(result.consume(), [{"id": 1}])

        self.session.execute("function lower(value){ value }")
        self.assertEqual(self.session.execute('lower("UNCHANGED")'), "UNCHANGED")
        self.assertEqual(self.session.execute('upper("works")'), "WORKS")


if __name__ == "__main__":
    unittest.main()
