import unittest
from dataclasses import FrozenInstanceError
from unittest.mock import patch

from datasets.table import TableDataset
from engine import NeoDBEngine
from neoql.selection import (
    FilterPlan,
    LimitPlan,
    OffsetPlan,
    OrderPlan,
    ProjectionPlan,
    Selection,
)


class LazySelectionTests(unittest.TestCase):
    def setUp(self):
        self.table = TableDataset(
            "users",
            {
                "id": {"type": "int"},
                "name": {"type": "str(50)"},
                "age": {"type": "int"},
            },
        )
        self.table.insert_many(
            [
                {"id": 1, "name": "Alice", "age": 30},
                {"id": 2, "name": "Ben", "age": 20},
                {"id": 3, "name": "Clara", "age": 40},
            ]
        )

    def test_query_builds_without_scanning_and_consumes_lazily(self):
        with patch.object(
            self.table,
            "_selection_records",
            wraps=self.table._selection_records,
        ) as scan:
            selection = self.table.query(
                {
                    "action": "select",
                    "filter": {"field": "age", "op": ">=", "value": 20},
                    "select": ["name", "age"],
                    "order_by": [{"field": "age", "direction": "desc"}],
                    "offset": 1,
                    "limit": 1,
                }
            )
            self.assertIsInstance(selection, Selection)
            scan.assert_not_called()
            self.assertEqual(selection.consume(), [{"name": "Alice", "age": 30}])
            scan.assert_called_once()

    def test_engine_dataset_invocation_returns_selection(self):
        engine = NeoDBEngine()
        engine.datasets["users"] = self.table
        result = engine.execute_query(
            {
                "action": "select",
                "dataset": "users",
                "filter": {"field": "age", "op": ">", "value": 30},
            }
        )
        self.assertIsInstance(result, Selection)
        self.assertEqual(result.consume(), [{"id": 3, "name": "Clara", "age": 40}])

    def test_transformations_append_immutable_plan_nodes(self):
        original = Selection(self.table)
        filtered = original.where({"field": "age", "op": ">", "value": 20})
        projected = filtered.project("name")
        ordered = projected.order(("name", "desc"))
        paged = ordered.offset(1).limit(2)

        self.assertEqual(original.plan, ())
        self.assertIsInstance(filtered.plan[-1], FilterPlan)
        self.assertIsInstance(projected.plan[-1], ProjectionPlan)
        self.assertIsInstance(ordered.plan[-1], OrderPlan)
        self.assertIsInstance(paged.plan[-2], OffsetPlan)
        self.assertIsInstance(paged.plan[-1], LimitPlan)
        with self.assertRaises(TypeError):
            filtered.plan[0].predicate["value"] = 99
        with self.assertRaises(FrozenInstanceError):
            filtered._plan = ()

    def test_consumption_reads_current_source_and_returns_detached_rows(self):
        selection = Selection(self.table).order(("id", "asc"))
        self.table.insert({"id": 4, "name": "Dora", "age": 25})
        consumed = selection.consume()
        self.assertEqual([row["id"] for row in consumed], [1, 2, 3, 4])
        consumed[0]["name"] = "changed"
        self.assertEqual(self.table.rows[0]["name"], "Alice")

    def test_sequence_consumption_boundaries(self):
        selection = Selection(self.table).order(("id", "asc")).limit(2)
        self.assertEqual(len(selection), 2)
        self.assertEqual(selection[0]["id"], 1)
        self.assertEqual([row["id"] for row in selection], [1, 2])
        self.assertIn("Selection(dataset='users'", repr(selection))


if __name__ == "__main__":
    unittest.main()
