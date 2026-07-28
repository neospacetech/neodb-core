import unittest

from cli.__main__ import (
    parse_cli_command,
    parse_filters,
    parse_object,
    parse_schema,
)
from engine import NeoDBEngine


class NeoQLParserTests(unittest.TestCase):
    def test_schema_preserves_parameterized_types_and_constraints(self):
        self.assertEqual(
            parse_schema("id(int, pk), name(str(255)), email(str(255), unique, index)"),
            {
                "id": {"type": "int", "constraints": ["pk"]},
                "name": {"type": "str(255)"},
                "email": {
                    "type": "str(255)",
                    "constraints": ["unique", "index"],
                },
            },
        )

    def test_record_literals_support_quotes_commas_and_scalars(self):
        self.assertEqual(
            parse_object('{id=1, name="Alice, A.", active=true, score=4.5}'),
            {"id": 1, "name": "Alice, A.", "active": True, "score": 4.5},
        )

    def test_boolean_predicates(self):
        self.assertEqual(
            parse_filters('{age>=18 && name startsWith "Al"}'),
            {
                "and": [
                    {"field": "age", "op": ">=", "value": 18},
                    {"field": "name", "op": "startsWith", "value": "Al"},
                ]
            },
        )

    def test_selection_method_chain(self):
        self.assertEqual(
            parse_cli_command(
                'users({age>=18}).(name, age).order(age desc).limit(5).offset(1)'
            ),
            {
                "action": "select",
                "dataset": "users",
                "filter": {"field": "age", "op": ">=", "value": 18},
                "select": ["name", "age"],
                "order_by": [{"field": "age", "direction": "desc"}],
                "limit": 5,
                "offset": 1,
            },
        )


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = NeoDBEngine()
        self.engine.execute_query(
            parse_cli_command(
                "create dataset users(table{id(int, pk), name(str(255)), age(int)})"
            )
        )

    def execute(self, neoql):
        return self.engine.execute_query(parse_cli_command(neoql))

    def test_table_insert_select_projection_and_pagination(self):
        result = self.execute(
            'add {id=1, name="Alice", age=25}, '
            '{id=2, name="Ben", age=17}, '
            '{id=3, name="Alicia", age=30} into users'
        )
        self.assertEqual(result, {"status": "success", "inserted": 3})
        self.assertEqual(
            self.execute(
                'users({age>=18 && name startsWith "Ali"}).'
                "(name, age).order(age desc).limit(1)"
            ),
            [{"name": "Alicia", "age": 30}],
        )

    def test_schema_rejects_unknown_fields(self):
        with self.assertRaisesRegex(ValueError, "Unknown fields"):
            self.execute('add {id=1, nickname="Al"} into users')

    def test_duplicate_dataset_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.engine.execute_query(
                parse_cli_command("create dataset users(graph{id(int, pk)})")
            )


if __name__ == "__main__":
    unittest.main()
