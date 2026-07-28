import unittest

from datasets.base import BaseDataset
from datasets.graph import GraphDataset
from datasets.kvs import KVSDataset
from datasets.table import TableDataset
from neoql.predicates import PredicateEvaluationError


class FilterTests(unittest.TestCase):
    def test_boolean_and_string_operators(self):
        record = {"name": "Alice", "roles": ["admin", "author"], "age": 30}
        self.assertTrue(
            BaseDataset._apply_filter(
                record,
                {
                    "and": [
                        {"field": "name", "op": "endsWith", "value": "ice"},
                        {"field": "roles", "op": "contains", "value": "admin"},
                        {"field": "age", "op": ">", "value": 20},
                    ]
                },
            )
        )
        self.assertTrue(
            BaseDataset._apply_filter(
                record,
                {
                    "or": [
                        {"field": "age", "op": "<", "value": 10},
                        {"field": "name", "op": "matches", "value": "^Ali"},
                    ]
                },
            )
        )
        self.assertTrue(
            BaseDataset._apply_filter(
                record,
                {"not": {"field": "age", "op": "<=", "value": 20}},
            )
        )

    def test_missing_values_and_unknown_operators_are_errors(self):
        with self.assertRaises(PredicateEvaluationError):
            BaseDataset._apply_filter({}, {"field": "missing", "op": ">", "value": 1})
        with self.assertRaises(PredicateEvaluationError):
            BaseDataset._apply_filter(
                {"value": 1}, {"field": "value", "op": "unknown", "value": 1}
            )


class GraphDatasetTests(unittest.TestCase):
    def setUp(self):
        self.graph = GraphDataset("people")

    def test_insert_filter_project_order_and_page(self):
        inserted = self.graph.query(
            {
                "action": "insert",
                "objects": [
                    {"id": 1, "name": "Alice", "age": 30},
                    {"id": 2, "name": "Ben", "age": 20},
                    {"id": 3, "name": "Clara", "age": 40},
                ],
            }
        )
        self.assertEqual(inserted["inserted_ids"], [1, 2, 3])
        self.assertEqual(
            self.graph.query(
                {
                    "action": "select",
                    "filter": {"field": "age", "op": ">=", "value": 20},
                    "select": ["name", "age"],
                    "order_by": [{"field": "age", "direction": "desc"}],
                    "offset": 1,
                    "limit": 1,
                }
            ),
            [{"name": "Alice", "age": 30}],
        )


class KVSDatasetTests(unittest.TestCase):
    def setUp(self):
        self.dataset = KVSDataset()

    def test_crud_and_query(self):
        self.assertEqual(
            self.dataset.query(
                {
                    "action": "insert",
                    "objects": [
                        {"key": "a", "value": 2},
                        {"key": "b", "value": 1},
                    ],
                }
            ),
            {"status": "success", "inserted": 2},
        )
        self.assertEqual(self.dataset.get("a"), 2)
        self.assertEqual(self.dataset.get("missing", 0), 0)
        self.assertEqual(set(self.dataset.keys()), {"a", "b"})
        self.assertEqual(
            self.dataset.query(
                {
                    "action": "select",
                    "filter": {"field": "value", "op": ">", "value": 0},
                    "select": ["key", "value"],
                    "order_by": [{"field": "value", "direction": "asc"}],
                    "limit": 1,
                }
            ),
            [{"key": "b", "value": 1}],
        )
        self.dataset.delete("a")
        self.assertIsNone(self.dataset.get("a"))

    def test_rejects_unsupported_action(self):
        with self.assertRaises(NotImplementedError):
            self.dataset.query({"action": "delete"})


class TableDatasetTests(unittest.TestCase):
    def test_insert_type_and_delete(self):
        table = TableDataset("users", {"id": {"type": "int"}})
        with self.assertRaises(TypeError):
            table.insert([1])
        table.insert({"id": 1})
        table.insert({"id": 2})
        table.delete(lambda row: row["id"] == 1)
        self.assertEqual(table.rows, [{"id": 2}])

    def test_rejects_unsupported_action(self):
        table = TableDataset("users")
        with self.assertRaises(NotImplementedError):
            table.query({"action": "truncate"})


if __name__ == "__main__":
    unittest.main()
