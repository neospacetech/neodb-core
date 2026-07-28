import unittest
from unittest.mock import patch

from datasets.table import TableDataset
from neoql.errors import EngineError
from neoql.selection import Selection


def table(name, fields, rows):
    dataset = TableDataset(
        name,
        {field: {"type": field_type} for field, field_type in fields.items()},
    )
    dataset.insert_many(rows)
    return dataset


class UnarySelectionTests(unittest.TestCase):
    def test_unique_sort_reverse_and_field_distinct(self):
        dataset = table(
            "people",
            {"id": "int", "name": "str(20)"},
            [
                {"id": 2, "name": "Ben"},
                {"id": 1, "name": "Alice"},
                {"id": 3, "name": "Ben"},
                {"id": 1, "name": "Alice"},
            ],
        )
        selection = Selection(dataset)
        self.assertEqual(
            selection.unique().sort("id").consume(),
            [
                {"id": 1, "name": "Alice"},
                {"id": 2, "name": "Ben"},
                {"id": 3, "name": "Ben"},
            ],
        )
        self.assertEqual(
            selection.distinct("name").reverse().consume(),
            [
                {"id": 1, "name": "Alice"},
                {"id": 2, "name": "Ben"},
            ],
        )

    def test_flatten_and_expand(self):
        dataset = table(
            "people",
            {"id": "int", "tags": "list(str(20))", "profile": "json"},
            [
                {
                    "id": 1,
                    "tags": ["admin", "author"],
                    "profile": {"name": "Alice", "active": True},
                },
                {
                    "id": 2,
                    "tags": [],
                    "profile": {"name": "Ben", "active": False},
                },
            ],
        )
        selection = Selection(dataset)
        self.assertEqual(
            selection.flatten("tags").project("id", "tags").consume(),
            [{"id": 1, "tags": "admin"}, {"id": 1, "tags": "author"}],
        )
        self.assertEqual(
            selection.expand("profile").consume(),
            [
                {
                    "id": 1,
                    "tags": ["admin", "author"],
                    "name": "Alice",
                    "active": True,
                },
                {
                    "id": 2,
                    "tags": [],
                    "name": "Ben",
                    "active": False,
                },
            ],
        )

    def test_flatten_type_and_expand_collision_are_structured(self):
        scalar = table("scalar", {"id": "int"}, [{"id": 1}])
        with self.assertRaises(EngineError) as raised:
            Selection(scalar).flatten("id").consume()
        self.assertEqual(raised.exception.code, "type_mismatch")

        nested = table(
            "nested",
            {"id": "int", "profile": "json"},
            [{"id": 1, "profile": {"id": 2}}],
        )
        with self.assertRaises(EngineError) as raised:
            Selection(nested).expand("profile").consume()
        self.assertEqual(raised.exception.code, "schema_mismatch")

    def test_composed_methods_remain_lazy(self):
        dataset = table(
            "people",
            {"id": "int", "tags": "list(str(20))"},
            [{"id": 1, "tags": ["a", "b"]}],
        )
        with patch.object(
            dataset,
            "_selection_records",
            wraps=dataset._selection_records,
        ) as scan:
            selection = (
                Selection(dataset)
                .where({"field": "id", "op": "=", "value": 1})
                .flatten("tags")
                .unique()
                .sort("tags")
                .reverse()
            )
            self.assertIsInstance(selection, Selection)
            scan.assert_not_called()
            self.assertEqual(len(selection.consume()), 2)
            scan.assert_called_once()


class SelectionAlgebraTests(unittest.TestCase):
    def setUp(self):
        self.left = Selection(
            table(
                "left",
                {"id": "int"},
                [{"id": 1}, {"id": 2}, {"id": 2}],
            )
        )
        self.right = Selection(
            table(
                "right",
                {"id": "int"},
                [{"id": 2}, {"id": 3}, {"id": 3}],
            )
        )

    def test_stable_distinct_set_algebra(self):
        self.assertEqual(self.left + self.right, [{"id": 1}, {"id": 2}, {"id": 3}])
        self.assertEqual(self.left & self.right, [{"id": 2}])
        self.assertEqual(self.left - self.right, [{"id": 1}])
        self.assertEqual(self.left ^ self.right, [{"id": 1}, {"id": 3}])

    def test_cartesian_product_is_nested_and_preserves_multiplicity(self):
        product = self.left.limit(2) * self.right.limit(2)
        self.assertIsInstance(product, Selection)
        self.assertEqual(
            product.consume(),
            [
                {"left": {"id": 1}, "right": {"id": 2}},
                {"left": {"id": 1}, "right": {"id": 3}},
                {"left": {"id": 2}, "right": {"id": 2}},
                {"left": {"id": 2}, "right": {"id": 3}},
            ],
        )
        full_product = (self.left * self.right).consume()
        self.assertEqual(len(full_product), 9)
        self.assertEqual(
            full_product.count({"left": {"id": 2}, "right": {"id": 3}}),
            4,
        )

    def test_schema_mismatch_is_rejected_at_consumption(self):
        incompatible = Selection(
            table("names", {"name": "str(20)"}, [{"name": "Alice"}])
        )
        combined = self.left.union(incompatible)
        self.assertIsInstance(combined, Selection)
        with self.assertRaises(EngineError) as raised:
            combined.consume()
        self.assertEqual(raised.exception.code, "schema_mismatch")

    def test_empty_selection_is_schema_compatible(self):
        empty = self.left.where({"field": "id", "op": ">", "value": 100})
        self.assertEqual(empty.union(self.right), [{"id": 2}, {"id": 3}])


if __name__ == "__main__":
    unittest.main()
