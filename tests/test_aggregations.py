import unittest
from unittest.mock import patch

from cli.__main__ import parse_cli_command
from datasets.table import TableDataset
from engine import NeoDBEngine
from neoql.errors import EngineError, NeoQLSyntaxError, UnknownFieldError
from neoql.parser import parse_statement, statement_to_query
from neoql.selection import Aggregation, Selection


def scores_table() -> TableDataset:
    dataset = TableDataset(
        "scores",
        {
            "team": {"type": "nullable(str(20))"},
            "score": {"type": "nullable(float)"},
            "name": {"type": "str(20)"},
        },
    )
    dataset.insert_many(
        [
            {"team": "red", "score": 1, "name": "A"},
            {"team": "blue", "score": 4, "name": "D"},
            {"team": "red", "score": 3, "name": "C"},
            {"team": None, "score": None, "name": "B"},
            {"team": "blue", "score": 8, "name": "E"},
        ]
    )
    return dataset


class AggregationTests(unittest.TestCase):
    def setUp(self):
        self.dataset = scores_table()
        self.selection = Selection(self.dataset)

    def test_ungrouped_aggregates_are_deterministic(self):
        expected = {
            "count": 5,
            "sum": 16.0,
            "avg": 4.0,
            "min": 1.0,
            "max": 8.0,
            "median": 3.5,
            "std": 2.5495097567963922,
        }
        aggregates = {
            "count": self.selection.count(),
            "sum": self.selection.sum("score"),
            "avg": self.selection.avg("score"),
            "min": self.selection.min("score"),
            "max": self.selection.max("score"),
            "median": self.selection.median("score"),
            "std": self.selection.std("score"),
        }
        for operation, aggregate in aggregates.items():
            with self.subTest(operation=operation):
                self.assertIsInstance(aggregate, Aggregation)
                self.assertAlmostEqual(aggregate.consume(), expected[operation])

    def test_grouped_aggregates_preserve_first_seen_group_order(self):
        self.assertEqual(
            self.selection.limit(3).group("team").consume(),
            [
                {
                    "team": "red",
                    "records": [
                        {"team": "red", "score": 1.0, "name": "A"},
                        {"team": "red", "score": 3.0, "name": "C"},
                    ],
                },
                {
                    "team": "blue",
                    "records": [{"team": "blue", "score": 4.0, "name": "D"}],
                },
            ],
        )
        self.assertEqual(
            self.selection.group("team").count().consume(),
            [
                {"team": "red", "count": 2},
                {"team": "blue", "count": 2},
                {"team": None, "count": 1},
            ],
        )
        self.assertEqual(
            self.selection.group("team").avg("score").consume(),
            [
                {"team": "red", "avg": 2.0},
                {"team": "blue", "avg": 6.0},
                {"team": None, "avg": None},
            ],
        )

    def test_empty_null_and_incompatible_values_have_defined_behavior(self):
        empty = self.selection.where({"field": "score", "op": ">", "value": 100})
        self.assertEqual(empty.count().consume(), 0)
        self.assertEqual(empty.sum("score").consume(), 0)
        for operation in ["avg", "min", "max", "median", "std"]:
            with self.subTest(operation=operation):
                self.assertIsNone(getattr(empty, operation)("score").consume())
        self.assertEqual(empty.group("team").count().consume(), [])

        with self.assertRaises(EngineError) as raised:
            self.selection.sum("name").consume()
        self.assertEqual(raised.exception.code, "invalid_aggregation")
        with self.assertRaises(UnknownFieldError):
            empty.avg("missing").consume()

    def test_aggregation_is_lazy_until_consumed(self):
        with patch.object(
            self.dataset,
            "_selection_records",
            wraps=self.dataset._selection_records,
        ) as scan:
            aggregate = self.selection.where(
                {"field": "score", "op": ">=", "value": 3}
            ).sum("score")
            scan.assert_not_called()
            self.assertEqual(aggregate.consume(), 15.0)
            scan.assert_called_once()


class AggregationSyntaxTests(unittest.TestCase):
    def test_parser_compiles_grouped_and_ungrouped_aggregates(self):
        self.assertEqual(
            statement_to_query(parse_statement("scores().sum(score)")),
            {
                "action": "select",
                "dataset": "scores",
                "filter": None,
                "aggregate": {"operation": "sum", "field": "score"},
            },
        )
        self.assertEqual(
            statement_to_query(
                parse_statement("scores({score>0}).group(team).median(score)")
            ),
            {
                "action": "select",
                "dataset": "scores",
                "filter": {"field": "score", "op": ">", "value": 0},
                "group_by": "team",
                "aggregate": {"operation": "median", "field": "score"},
            },
        )

    def test_invalid_aggregate_chains_are_source_located(self):
        invalid = [
            "scores().count(score)",
            "scores().sum()",
            "scores().group()",
            "scores().group(team).limit(1)",
            "scores().group(team).order(score)",
            "scores().count().limit(1)",
        ]
        for source in invalid:
            with self.subTest(source=source), self.assertRaises(NeoQLSyntaxError):
                statement_to_query(parse_statement(source))

    def test_engine_returns_lazy_aggregate_from_neoql(self):
        engine = NeoDBEngine()
        engine.datasets["scores"] = scores_table()
        result = engine.execute_query(
            parse_cli_command("scores().group(team).max(score)")
        )
        self.assertIsInstance(result, Aggregation)
        self.assertEqual(
            result.consume(),
            [
                {"team": "red", "max": 3.0},
                {"team": "blue", "max": 8.0},
                {"team": None, "max": None},
            ],
        )


if __name__ == "__main__":
    unittest.main()
