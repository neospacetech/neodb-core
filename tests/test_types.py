import unittest
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from cli.__main__ import parse_cli_command
from neoql.references import ReferenceValue
from neoql.types import (
    NeoQLTypeError,
    TypeDescriptor,
    TypeKind,
    cast_value,
    infer_type,
    parse_type,
)


class TypeParsingTests(unittest.TestCase):
    def test_all_primitive_types(self):
        sources = [
            "int",
            "float",
            "decimal",
            "bool",
            "char",
            "str(255)",
            "text",
            "date",
            "time",
            "datetime",
            "timestamp",
            "duration",
            "uuid",
            "bytes",
            "json",
        ]
        self.assertEqual(
            [parse_type(source).display() for source in sources],
            sources,
        )

    def test_composite_and_reference_types(self):
        sources = [
            "list(int)",
            "set(uuid)",
            "map(str(20), nullable(json))",
            "tuple(int, str(10), bool)",
            "nullable(datetime)",
            'enum("draft", "published")',
            "users",
        ]
        self.assertEqual(
            [parse_type(source).display() for source in sources],
            sources,
        )
        self.assertEqual(parse_type("users").kind, TypeKind.REFERENCE)

    def test_parameter_validation(self):
        invalid = [
            "str",
            "str(0)",
            "int(1)",
            "list",
            "list(int, str(2))",
            "map(int)",
            "tuple",
            "nullable(int, str(2))",
            "nullable(nullable(int))",
            "enum",
            'enum("a", "a")',
            "users(int)",
        ]
        for source in invalid:
            with self.subTest(source=source), self.assertRaises(NeoQLTypeError):
                parse_type(source)

    def test_dataset_compilation_runs_semantic_type_validation(self):
        with self.assertRaisesRegex(
            NeoQLTypeError, "str requires one positive integer length"
        ):
            parse_cli_command("create dataset users(table{name(str)})")

    def test_equality_display_and_serialization_round_trip(self):
        descriptor = parse_type("map(str(50), list(nullable(tuple(uuid, datetime))))")
        restored = TypeDescriptor.from_dict(descriptor.to_dict())
        self.assertEqual(restored, descriptor)
        self.assertEqual(restored.display(), descriptor.display())
        with self.assertRaises(NeoQLTypeError):
            TypeDescriptor.from_dict({"kind": "not-a-type"})
        with self.assertRaises(NeoQLTypeError):
            TypeDescriptor.from_dict({"kind": "list", "arguments": "int"})


class InferenceTests(unittest.TestCase):
    def test_scalar_inference(self):
        values = [
            (True, TypeKind.BOOL),
            (1, TypeKind.INT),
            (1.5, TypeKind.FLOAT),
            (Decimal("1.2"), TypeKind.DECIMAL),
            ("x", TypeKind.CHAR),
            ("hello", TypeKind.STR),
            (date(2026, 1, 1), TypeKind.DATE),
            (time(12, 0), TypeKind.TIME),
            (datetime(2026, 1, 1), TypeKind.DATETIME),
            (timedelta(seconds=5), TypeKind.DURATION),
            (UUID(int=0), TypeKind.UUID),
            (b"data", TypeKind.BYTES),
        ]
        for value, kind in values:
            with self.subTest(value=value):
                self.assertEqual(infer_type(value).kind, kind)

    def test_collection_inference(self):
        self.assertEqual(infer_type([1, 2]), parse_type("list(int)"))
        self.assertEqual(infer_type({1, 2}), parse_type("set(int)"))
        self.assertEqual(
            infer_type({"a": 1, "b": 2}),
            parse_type("map(char, int)"),
        )
        self.assertEqual(
            infer_type((1, "name", True)),
            parse_type("tuple(int, str(4), bool)"),
        )

    def test_ambiguous_or_mixed_literals_require_context(self):
        values = [None, [], set(), {}, (), [1, "two"]]
        for value in values:
            with self.subTest(value=value), self.assertRaises(NeoQLTypeError):
                infer_type(value)


class CastingTests(unittest.TestCase):
    def test_scalar_casts(self):
        self.assertEqual(cast_value("42", parse_type("int")), 42)
        self.assertEqual(cast_value("1.25", parse_type("decimal")), Decimal("1.25"))
        self.assertTrue(cast_value("true", parse_type("bool")))
        self.assertEqual(cast_value(7, parse_type("str(2)")), "7")
        self.assertEqual(
            cast_value("2026-01-02", parse_type("date")),
            date(2026, 1, 2),
        )
        self.assertEqual(
            cast_value(0, parse_type("timestamp")),
            datetime(1970, 1, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(
            cast_value(5, parse_type("duration")),
            timedelta(seconds=5),
        )
        reference = ReferenceValue("users", (("id", 1),))
        self.assertEqual(cast_value(reference, parse_type("users")), reference)
        self.assertEqual(infer_type(reference), parse_type("users"))
        self.assertEqual(
            cast_value(str(UUID(int=0)), parse_type("uuid")),
            UUID(int=0),
        )

    def test_composite_nullable_and_enum_casts(self):
        self.assertEqual(
            cast_value(["1", "2"], parse_type("list(int)")),
            [1, 2],
        )
        self.assertEqual(
            cast_value({"1": "true"}, parse_type("map(int, bool)")),
            {1: True},
        )
        self.assertEqual(
            cast_value(["1", 2], parse_type("tuple(int, str(2))")),
            (1, "2"),
        )
        self.assertIsNone(cast_value(None, parse_type("nullable(int)")))
        self.assertEqual(
            cast_value("draft", parse_type('enum("draft", "published")')),
            "draft",
        )

    def test_invalid_casts_are_structured(self):
        cases = [
            ("many", "char"),
            ("too long", "str(3)"),
            ("maybe", "bool"),
            (None, "int"),
            ("missing", 'enum("draft", "published")'),
            ([1], "tuple(int, int)"),
            ({"not-json"}, "json"),
            (1, "users"),
        ]
        for value, target in cases:
            with (
                self.subTest(value=value, target=target),
                self.assertRaises(NeoQLTypeError),
            ):
                cast_value(value, parse_type(target))


if __name__ == "__main__":
    unittest.main()
