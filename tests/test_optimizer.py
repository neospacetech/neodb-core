import unittest
from unittest.mock import patch

from cli.__main__ import parse_cli_command
from datasets.graph import GraphDataset
from datasets.table import TableDataset
from engine import NeoDBEngine
from neoql.optimizer import optimize_plan
from neoql.selection import (
    FilterPlan,
    IndexLookupPlan,
    LimitPlan,
    OffsetPlan,
    ProjectionPlan,
    ReversePlan,
    Selection,
)


class OptimizerTests(unittest.TestCase):
    def setUp(self):
        self.table = TableDataset(
            "users",
            {
                "id": {"type": "int", "constraints": ["pk"]},
                "age": {"type": "int", "constraints": ["index"]},
                "name": {"type": "str(20)"},
            },
        )
        self.table.insert_many(
            [
                {"id": 1, "age": 20, "name": "A"},
                {"id": 2, "age": 30, "name": "B"},
                {"id": 3, "age": 30, "name": "C"},
            ]
        )

    def assert_equivalent(self, selection):
        self.assertEqual(
            selection.consume(optimize=False),
            selection.consume(optimize=True),
        )

    def test_pushdown_and_redundant_nodes_preserve_results(self):
        selection = (
            Selection(self.table)
            .project("id", "age", "name")
            .where({"field": "age", "op": "=", "value": 30})
            .project("id", "name")
            .offset(0)
            .offset(1)
            .offset(1)
            .limit(10)
            .limit(2)
            .reverse()
            .reverse()
        )
        result = optimize_plan(selection.plan, self.table)
        self.assertIn("predicate_pushdown", result.rules)
        self.assertIn("remove_zero_offset", result.rules)
        self.assertIn("merge_offsets", result.rules)
        self.assertIn("merge_limits", result.rules)
        self.assertIn("remove_double_reverse", result.rules)
        self.assertIsInstance(result.optimized[0], IndexLookupPlan)
        self.assert_equivalent(selection)

    def test_index_hook_is_used_for_indexed_equality(self):
        selection = Selection(self.table).where(
            {"field": "age", "op": "=", "value": 30}
        )
        with patch.object(
            self.table,
            "_index_lookup",
            wraps=self.table._index_lookup,
        ) as lookup:
            self.assertEqual([row["id"] for row in selection], [2, 3])
            lookup.assert_called_once()
        self.assertIsInstance(selection.optimized().plan[0], IndexLookupPlan)

    def test_graph_vector_and_empty_join_rules_are_reported(self):
        graph = GraphDataset("graph")
        graph.insert({"id": 1})
        graph.insert({"id": 2})
        graph.add_link(1, 2, label="friend")
        traversal = Selection(graph).traverse("friend", depth=3).limit(1)
        self.assertIn("graph_limit_pruning", traversal.explain()["rules"])

        vector = Selection(self.table).similarity("age", [1]).limit(1)
        self.assertIn("vector_limit_pruning", vector.explain()["rules"])

        empty = Selection(self.table).limit(0)
        product = Selection(self.table).product(empty)
        self.assertIn("join_elimination", product.explain()["rules"])
        self.assert_equivalent(product)

    def test_explain_contains_logical_and_optimized_plans(self):
        selection = (
            Selection(self.table)
            .where({"field": "id", "op": "=", "value": 1})
            .limit(5)
            .limit(1)
        )
        explain = selection.explain()
        self.assertEqual(explain["dataset"], "users")
        self.assertEqual(explain["logical"][0]["node"], "FilterPlan")
        self.assertEqual(explain["optimized"][0]["node"], "IndexLookupPlan")
        self.assertIn("index_selection", explain["rules"])
        self.assertIn("merge_limits", explain["rules"])

        engine = NeoDBEngine()
        engine.datasets["users"] = self.table
        query = parse_cli_command("users({id=1}).limit(5).explain()")
        self.assertTrue(query["explain"])
        rendered = engine.execute_query(query)
        self.assertEqual(rendered["optimized"][0]["node"], "IndexLookupPlan")

    def test_optimizer_leaves_unsafe_rewrites_untouched(self):
        plan = (
            ProjectionPlan(("id",)),
            ProjectionPlan(("name",)),
            OffsetPlan(1),
            FilterPlan({"field": "id", "op": "=", "value": 2}),
            ReversePlan(),
            LimitPlan(1),
        )
        result = optimize_plan(plan, self.table)
        self.assertEqual(result.optimized, plan)


if __name__ == "__main__":
    unittest.main()
