import unittest

from cli.__main__ import parse_cli_command
from datasets.document import DocumentDataset
from datasets.kvs import KVSDataset
from datasets.table import TableDataset
from engine import NeoDBEngine
from neoql.errors import EngineError
from neoql.parser import parse_statement, statement_to_query
from neoql.schema import ConstraintViolation, SchemaDefinitionError
from neoql.selection import Selection, SimilarityPlan


class DocumentAndKeyValueTests(unittest.TestCase):
    def test_shared_selection_contract_across_storage_models(self):
        table = TableDataset(
            "table_items",
            {"key": {"type": "str(10)"}, "value": {"type": "int"}},
        )
        document = DocumentDataset(
            "documents",
            {"key": {"type": "str(10)"}, "value": {"type": "int"}},
        )
        vector = DocumentDataset(
            "vectors",
            {
                "key": {"type": "str(10)"},
                "value": {"type": "int"},
                "embedding": {
                    "type": "list(float)",
                    "constraints": [
                        {"name": "vector", "arguments": [2]},
                    ],
                },
            },
        )
        key_value = KVSDataset("cache")
        for dataset in (table, document):
            dataset.insert_many([{"key": "a", "value": 1}, {"key": "b", "value": 2}])
        vector.insert_many(
            [
                {"key": "a", "value": 1, "embedding": [1, 0]},
                {"key": "b", "value": 2, "embedding": [0, 1]},
            ]
        )
        key_value.insert({"key": "a", "value": 1})
        key_value.insert({"key": "b", "value": 2})

        for dataset in (table, document, vector, key_value):
            with self.subTest(dataset=dataset.name):
                result = (
                    Selection(dataset)
                    .where({"field": "value", "op": ">", "value": 0})
                    .project("key", "value")
                    .order(("value", "desc"))
                    .offset(1)
                    .limit(1)
                    .consume()
                )
                self.assertEqual(result, [{"key": "a", "value": 1}])

    def test_document_dataset_is_schema_aware_and_lazy(self):
        engine = NeoDBEngine()
        engine.execute_query(
            parse_cli_command(
                "create dataset docs(document{id(int, pk), title(str(50)), data(json)})"
            )
        )
        self.assertIsInstance(engine.datasets["docs"], DocumentDataset)
        engine.execute_query(
            parse_cli_command(
                'add {id=1, title="One", data={rank=2}}, '
                '{id=2, title="Two", data={rank=1}} into docs'
            )
        )
        result = engine.execute_query(
            parse_cli_command("docs({id>=1}).(title).order(title desc).limit(1)")
        )
        self.assertIsInstance(result, Selection)
        self.assertEqual(result.consume(), [{"title": "Two"}])
        with self.assertRaises(ConstraintViolation):
            engine.execute_query(
                parse_cli_command('add {id=3, title="Three"} into docs')
            )

    def test_key_value_dataset_uses_normal_neoql_flows(self):
        engine = NeoDBEngine()
        engine.execute_query(parse_cli_command("create dataset cache(kv)"))
        self.assertIsInstance(engine.datasets["cache"], KVSDataset)
        engine.execute_query(
            parse_cli_command('add {key="a", value=2}, {key="b", value=1} into cache')
        )
        result = engine.execute_query(
            parse_cli_command('cache({key in ["a", "b"]}).order(value asc).limit(1)')
        )
        self.assertEqual(result.consume(), [{"key": "b", "value": 1}])
        with self.assertRaises(EngineError) as raised:
            engine.execute_query(
                {
                    "action": "insert",
                    "dataset": "cache",
                    "objects": [{"key": "bad"}],
                }
            )
        self.assertEqual(raised.exception.code, "invalid_record")


class VectorDatasetTests(unittest.TestCase):
    def setUp(self):
        self.engine = NeoDBEngine()
        self.engine.execute_query(
            parse_cli_command(
                "create dataset items("
                "vector{id(int, pk), embedding(list(float), vector(3))}"
                ")"
            )
        )
        self.engine.execute_query(
            parse_cli_command(
                "add {id=1, embedding=[1, 0, 0]}, "
                "{id=2, embedding=[0.8, 0.2, 0]}, "
                "{id=3, embedding=[0, 1, 0]} into items"
            )
        )

    def test_similarity_is_lazy_ranked_and_reports_scores(self):
        query = parse_cli_command(
            "items().similarity(embedding, [1, 0, 0], cosine).limit(2)"
        )
        self.assertEqual(
            query["similarity"],
            {
                "field": "embedding",
                "vector": [1, 0, 0],
                "metric": "cosine",
            },
        )
        result = self.engine.execute_query(query)
        self.assertIsInstance(result.plan[0], SimilarityPlan)
        rows = result.consume()
        self.assertEqual([row["id"] for row in rows], [1, 2])
        self.assertAlmostEqual(rows[0]["_distance"], 0.0)
        self.assertAlmostEqual(rows[0]["_similarity"], 1.0)

        projected = self.engine.execute_query(
            parse_cli_command(
                "items().similarity(embedding, [1, 0, 0])."
                "(id, _distance).order(_distance asc).limit(1)"
            )
        ).consume()
        self.assertEqual(projected, [{"id": 1, "_distance": 0.0}])

        euclidean = self.engine.execute_query(
            parse_cli_command("items().distance(embedding, [0, 1, 0]).limit(1)")
        ).consume()
        self.assertEqual(euclidean[0]["id"], 3)
        self.assertEqual(euclidean[0]["_distance"], 0.0)

    def test_vector_dimensions_and_index_fields_are_validated(self):
        with self.assertRaises(ConstraintViolation) as raised:
            self.engine.execute_query(
                parse_cli_command("add {id=4, embedding=[1, 2]} into items")
            )
        self.assertEqual(raised.exception.code, "vector_dimension")

        with self.assertRaises(EngineError) as raised:
            self.engine.execute_query(
                parse_cli_command("items().similarity(embedding, [1, 2], cosine)")
            ).consume()
        self.assertEqual(raised.exception.code, "vector_dimension")

        with self.assertRaises(SchemaDefinitionError):
            parse_cli_command("create dataset bad(vector{id(int, vector(3))})")

    def test_similarity_syntax_requires_the_vector_operation_first(self):
        with self.assertRaisesRegex(Exception, "must precede"):
            statement_to_query(
                parse_statement("items().limit(1).similarity(embedding, [1, 0, 0])")
            )


if __name__ == "__main__":
    unittest.main()
