import json
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

from cli.__main__ import parse_cli_command
from engine import NeoDBEngine
from neoql.errors import EngineError
from neoql.references import ReferenceValue
from neoql.schema import ConstraintViolation


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


class DurableEngineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def engine(self):
        return NeoDBEngine(self.path)

    def test_committed_state_survives_restart_across_storage_models(self):
        engine = self.engine()
        engine.execute_query(
            parse_cli_command(
                "create dataset users("
                "table{id(int, pk), email(str(100), unique, index)}"
                ")"
            )
        )
        engine.execute_query(
            parse_cli_command('add {id=1, email="a@example.com"} into users')
        )
        engine.execute_query(
            parse_cli_command(
                "create dataset managers(table{id(int, pk), name(str(30))})"
            )
        )
        engine.execute_query(
            parse_cli_command(
                "create dataset reports(table{id(int, pk), manager(managers)})"
            )
        )
        engine.execute_query(
            parse_cli_command('add {id=1, manager={id=7, name="Lead"}} into reports')
        )
        engine.execute_query(parse_cli_command("create dataset graph(graph)"))
        engine.execute_query(
            parse_cli_command('add {id=1, name="A"}, {id=2, name="B"} into graph')
        )
        engine.execute_query(
            parse_cli_command(
                "add link(label=friend) between graph({id=1}), graph({id=2})"
            )
        )
        engine.execute_query(parse_cli_command("create dataset cache(kv)"))
        engine.execute_query(
            parse_cli_command('add {key="answer", value=42} into cache')
        )
        engine.execute_query(
            parse_cli_command(
                "create dataset vectors("
                "vector{id(int, pk), embedding(list(float), vector(2))}"
                ")"
            )
        )
        engine.execute_query(
            parse_cli_command("add {id=1, embedding=[1, 0]} into vectors")
        )

        restarted = self.engine()
        self.assertEqual(
            list(restarted.execute_query(parse_cli_command("users()"))),
            [{"id": 1, "email": "a@example.com"}],
        )
        self.assertEqual(
            [
                row["id"]
                for row in restarted.execute_query(
                    parse_cli_command("graph({id=1}).traverse(friend)")
                )
            ],
            [2],
        )
        self.assertEqual(
            list(restarted.execute_query(parse_cli_command("cache()"))),
            [{"key": "answer", "value": 42}],
        )
        report = restarted.execute_query(parse_cli_command("reports()"))[0]
        self.assertEqual(
            report["manager"],
            ReferenceValue("managers", (("id", 7),)),
        )
        vector = restarted.execute_query(
            parse_cli_command("vectors().similarity(embedding, [1, 0]).limit(1)")
        )[0]
        self.assertEqual(vector["id"], 1)
        self.assertEqual(vector["_similarity"], 1.0)

    def test_wal_recovers_commit_interrupted_before_snapshot(self):
        engine = self.engine()
        engine.execute_query(
            parse_cli_command("create dataset users(table{id(int, pk)})")
        )
        assert engine._storage is not None
        with patch.object(
            engine._storage,
            "_write_snapshot",
            side_effect=EngineError("storage_io", "simulated"),
        ):
            engine.execute_query(parse_cli_command("add {id=1} into users"))
        self.assertEqual(
            list(engine.execute_query(parse_cli_command("users()"))),
            [{"id": 1}],
        )

        recovered = self.engine()
        self.assertEqual(
            list(recovered.execute_query(parse_cli_command("users()"))),
            [{"id": 1}],
        )
        self.assertEqual((self.path / "wal.jsonl").read_text(), "")

    def test_failed_transaction_never_reaches_durable_state(self):
        engine = self.engine()
        engine.execute_query(
            parse_cli_command("create dataset users(table{id(int, pk)})")
        )
        with self.assertRaises(ConstraintViolation):
            engine.execute_query(
                {
                    "action": "transaction",
                    "queries": [
                        parse_cli_command("add {id=1} into users"),
                        parse_cli_command("add {id=1} into users"),
                    ],
                }
            )
        restarted = self.engine()
        self.assertEqual(
            list(restarted.execute_query(parse_cli_command("users()"))),
            [],
        )

    def test_wal_failure_does_not_publish_commit(self):
        engine = self.engine()
        engine.execute_query(
            parse_cli_command("create dataset users(table{id(int, pk)})")
        )
        assert engine._storage is not None
        with (
            patch.object(
                engine._storage,
                "_append_wal",
                side_effect=EngineError("storage_io", "simulated"),
            ),
            self.assertRaises(EngineError),
        ):
            engine.execute_query(parse_cli_command("add {id=1} into users"))
        self.assertEqual(engine._committed_datasets["users"].rows, [])
        self.assertEqual(self.engine().datasets["users"].rows, [])

    def test_snapshot_corruption_and_version_are_structured(self):
        engine = self.engine()
        engine.execute_query(parse_cli_command("create dataset users(table)"))
        snapshot_path = self.path / "snapshot.json"
        envelope = json.loads(snapshot_path.read_text())
        envelope["checksum"] = "bad"
        snapshot_path.write_text(canonical(envelope))
        with self.assertRaises(EngineError) as raised:
            self.engine()
        self.assertEqual(raised.exception.code, "storage_corruption")

        envelope["checksum"] = sha256(canonical(envelope["state"]).encode()).hexdigest()
        envelope["version"] = 999
        snapshot_path.write_text(canonical(envelope))
        with self.assertRaises(EngineError) as raised:
            self.engine()
        self.assertEqual(raised.exception.code, "storage_version")

    def test_partial_wal_tail_is_ignored_after_checkpoint(self):
        engine = self.engine()
        engine.execute_query(parse_cli_command("create dataset users(table)"))
        with (self.path / "wal.jsonl").open("a") as wal:
            wal.write('{"partial":')
        restarted = self.engine()
        self.assertIn("users", restarted.datasets)

    def test_persisted_indexes_are_used_and_checked(self):
        engine = self.engine()
        engine.execute_query(
            parse_cli_command(
                "create dataset users("
                "table{id(int, pk), age(int, index), email(str(30), unique)}"
                ")"
            )
        )
        engine.execute_query(
            parse_cli_command(
                'add {id=1, age=20, email="a"}, {id=2, age=30, email="b"} into users'
            )
        )
        restarted = self.engine()
        table = restarted.datasets["users"]
        self.assertEqual(set(table.index_snapshot()), {"id", "age", "email"})
        with patch.object(
            table,
            "_selection_records",
            side_effect=AssertionError("index lookup fell back to scan"),
        ):
            rows = restarted.execute_query(
                parse_cli_command("users({age=30})")
            ).consume()
        self.assertEqual(rows, [{"id": 2, "age": 30, "email": "b"}])

        snapshot_path = self.path / "snapshot.json"
        envelope = json.loads(snapshot_path.read_text())
        dataset = envelope["state"]["datasets"][0]
        dataset["indexes"] = {"$type": "map", "items": []}
        envelope["checksum"] = sha256(canonical(envelope["state"]).encode()).hexdigest()
        snapshot_path.write_text(canonical(envelope))
        with self.assertRaises(EngineError) as raised:
            self.engine()
        self.assertEqual(raised.exception.code, "storage_corruption")


if __name__ == "__main__":
    unittest.main()
