import unittest

from cli.__main__ import parse_cli_command
from datasets.table import TableDataset
from engine import NeoDBEngine
from neoql.schema import (
    ConstraintViolation,
    DatasetSchema,
    SchemaDefinitionError,
)


class SchemaDefinitionTests(unittest.TestCase):
    def test_constraint_arguments_and_defaults_survive_compilation(self):
        query = parse_cli_command(
            """
            create dataset users(
                table{
                    id(int, pk),
                    name(str(20), default("Anonymous")),
                    nickname(nullable(str(20))),
                    email(str(100), unique, index),
                    embedding(list(float), vector),
                    bio(text, searchable),
                    created_at(datetime, readonly)
                }
            )
            """
        )
        self.assertEqual(
            query["schema"]["name"]["constraints"],
            [{"name": "default", "arguments": ["Anonymous"]}],
        )
        schema = DatasetSchema.from_mapping("users", query["schema"])
        self.assertEqual(schema.primary_key, ("id",))
        self.assertEqual(
            {
                metadata.field: {
                    "indexed": metadata.indexed,
                    "unique": metadata.unique,
                    "primary": metadata.primary,
                    "vector": metadata.vector,
                    "searchable": metadata.searchable,
                }
                for metadata in schema.indexes
            },
            {
                "id": {
                    "indexed": True,
                    "unique": True,
                    "primary": True,
                    "vector": False,
                    "searchable": False,
                },
                "email": {
                    "indexed": True,
                    "unique": True,
                    "primary": False,
                    "vector": False,
                    "searchable": False,
                },
                "embedding": {
                    "indexed": True,
                    "unique": False,
                    "primary": False,
                    "vector": True,
                    "searchable": False,
                },
                "bio": {
                    "indexed": True,
                    "unique": False,
                    "primary": False,
                    "vector": False,
                    "searchable": True,
                },
            },
        )

    def test_invalid_schema_declarations_are_rejected(self):
        invalid = [
            "create dataset x(table{id(int, mystery)})",
            "create dataset x(table{id(int, pk, nullable)})",
            "create dataset x(table{id(int, default)})",
            "create dataset x(table{id(int, unique(1))})",
            'create dataset x(table{id(int, default("not-an-int"))})',
            "create dataset x(table{id(int), id(int)})",
            "create dataset x(table{tags(list(str(10)), unique)})",
        ]
        for source in invalid:
            with self.subTest(source=source), self.assertRaises(SchemaDefinitionError):
                query = parse_cli_command(source)
                DatasetSchema.from_mapping("x", query["schema"])


class InsertConstraintTests(unittest.TestCase):
    def setUp(self):
        query = parse_cli_command(
            """
            create dataset users(
                table{
                    tenant(int, pk),
                    id(int, pk),
                    email(str(100), unique),
                    name(str(20), default("Anonymous")),
                    nickname(str(20), nullable),
                    created_by(str(20), readonly)
                }
            )
            """
        )
        self.table = TableDataset("users", query["schema"])

    def test_defaults_nullable_fields_and_types_are_normalized(self):
        inserted = self.table.insert(
            {
                "tenant": "1",
                "id": "2",
                "email": "a@example.com",
                "created_by": "system",
            }
        )
        self.assertEqual(
            inserted,
            {
                "tenant": 1,
                "id": 2,
                "email": "a@example.com",
                "name": "Anonymous",
                "nickname": None,
                "created_by": "system",
            },
        )

    def test_required_unknown_null_and_type_violations_are_structured(self):
        cases = [
            (
                {"tenant": 1},
                "required",
                "id",
            ),
            (
                {
                    "tenant": 1,
                    "id": 1,
                    "email": "a@example.com",
                    "created_by": "system",
                    "extra": True,
                },
                "unknown_field",
                "extra",
            ),
            (
                {
                    "tenant": 1,
                    "id": None,
                    "email": "a@example.com",
                    "created_by": "system",
                },
                "null",
                "id",
            ),
            (
                {
                    "tenant": "nope",
                    "id": 1,
                    "email": "a@example.com",
                    "created_by": "system",
                },
                "type",
                "tenant",
            ),
        ]
        for record, code, field in cases:
            with (
                self.subTest(code=code),
                self.assertRaises(ConstraintViolation) as raised,
            ):
                self.table.insert(record)
            error = raised.exception
            self.assertEqual(error.code, code)
            self.assertEqual(error.field, field)
            self.assertEqual(error.to_dict()["error"], "constraint_violation")
            self.assertEqual(self.table.rows, [])

    def test_composite_primary_key_and_unique_constraints(self):
        self.table.insert(
            {
                "tenant": 1,
                "id": 1,
                "email": "a@example.com",
                "created_by": "system",
            }
        )
        with self.assertRaisesRegex(
            ConstraintViolation, "Primary-key value already exists"
        ):
            self.table.insert(
                {
                    "tenant": 1,
                    "id": 1,
                    "email": "b@example.com",
                    "created_by": "system",
                }
            )
        with self.assertRaisesRegex(
            ConstraintViolation, "Unique value.*already exists"
        ):
            self.table.insert(
                {
                    "tenant": 2,
                    "id": 1,
                    "email": "a@example.com",
                    "created_by": "system",
                }
            )

    def test_batch_insert_is_atomic(self):
        with self.assertRaises(ConstraintViolation):
            self.table.insert_many(
                [
                    {
                        "tenant": 1,
                        "id": 1,
                        "email": "same@example.com",
                        "created_by": "system",
                    },
                    {
                        "tenant": 1,
                        "id": 2,
                        "email": "same@example.com",
                        "created_by": "system",
                    },
                ]
            )
        self.assertEqual(self.table.rows, [])


class UpdateConstraintTests(unittest.TestCase):
    def setUp(self):
        self.table = TableDataset(
            "users",
            {
                "id": {"type": "int", "constraints": ["pk", "readonly"]},
                "email": {"type": "str(100)", "constraints": ["unique"]},
                "age": {"type": "int"},
            },
        )
        self.table.insert_many(
            [
                {"id": 1, "email": "a@example.com", "age": 20},
                {"id": 2, "email": "b@example.com", "age": 30},
            ]
        )

    def test_updates_are_typed_filtered_and_reported(self):
        result = self.table.query(
            {
                "action": "update",
                "filter": {"field": "id", "op": "=", "value": 1},
                "values": {"age": "21"},
            }
        )
        self.assertEqual(result, {"status": "success", "updated": 1})
        self.assertEqual(self.table.rows[0]["age"], 21)

    def test_update_enforces_unknown_null_readonly_and_unique(self):
        cases = [
            ({"missing": 1}, "unknown_field"),
            ({"age": None}, "null"),
            ({"id": 3}, "readonly"),
            ({"email": "same@example.com"}, "unique"),
        ]
        for changes, code in cases:
            before = [dict(row) for row in self.table.rows]
            with (
                self.subTest(code=code),
                self.assertRaises(ConstraintViolation) as raised,
            ):
                if code == "unique":
                    self.table.update(changes)
                else:
                    self.table.update(changes, where=lambda row: row["id"] == 1)
            self.assertEqual(raised.exception.code, code)
            self.assertEqual(self.table.rows, before)


class EngineConstraintTests(unittest.TestCase):
    def test_engine_uses_schema_contract_for_batch_insert(self):
        engine = NeoDBEngine()
        engine.execute_query(
            parse_cli_command("create dataset users(table{id(int, pk), name(str(10))})")
        )
        with self.assertRaises(ConstraintViolation):
            engine.execute_query(
                {
                    "action": "insert",
                    "dataset": "users",
                    "objects": [
                        {"id": 1, "name": "Alice"},
                        {"id": 1, "name": "Alicia"},
                    ],
                }
            )
        self.assertEqual(engine.datasets["users"].rows, [])


if __name__ == "__main__":
    unittest.main()
