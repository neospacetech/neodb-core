import unittest

from cli.__main__ import compile_source, parse_cli_command
from engine import NeoDBEngine
from neoql.errors import EngineError
from neoql.schema import ConstraintViolation


class EngineTransactionTests(unittest.TestCase):
    def setUp(self):
        self.engine = NeoDBEngine()
        self.engine.execute_query(
            parse_cli_command("create dataset users(table{id(int, pk)})")
        )
        self.engine.execute_query(parse_cli_command("add {id=1} into users"))

    def ids(self):
        return [
            row["id"] for row in self.engine.execute_query(parse_cli_command("users()"))
        ]

    def test_uncommitted_changes_are_isolated_and_abort_restores_state(self):
        committed_selection = self.engine.execute_query(parse_cli_command("users()"))
        transaction_id = self.engine.begin_transaction()
        self.engine.execute_query(parse_cli_command("add {id=2} into users"))
        self.assertEqual(self.ids(), [1, 2])
        self.assertEqual(
            [row["id"] for row in committed_selection.consume()],
            [1],
        )
        self.engine.abort_transaction(transaction_id)
        self.assertEqual(self.ids(), [1])

    def test_commit_publishes_atomically(self):
        transaction_id = self.engine.begin_transaction()
        self.engine.execute_query(parse_cli_command("add {id=2} into users"))
        self.engine.commit_transaction(transaction_id)
        self.assertEqual(self.ids(), [1, 2])

    def test_nested_commit_merges_and_outer_abort_discards_everything(self):
        outer = self.engine.begin_transaction()
        self.engine.execute_query(parse_cli_command("add {id=2} into users"))
        inner = self.engine.begin_transaction()
        self.engine.execute_query(parse_cli_command("add {id=3} into users"))
        self.engine.commit_transaction(inner)
        self.assertEqual(self.ids(), [1, 2, 3])
        self.engine.abort_transaction(outer)
        self.assertEqual(self.ids(), [1])

    def test_nested_abort_preserves_outer_work(self):
        outer = self.engine.begin_transaction()
        self.engine.execute_query(parse_cli_command("add {id=2} into users"))
        inner = self.engine.begin_transaction()
        self.engine.execute_query(parse_cli_command("add {id=3} into users"))
        self.engine.abort_transaction(inner)
        self.assertEqual(self.ids(), [1, 2])
        self.engine.commit_transaction(outer)
        self.assertEqual(self.ids(), [1, 2])

    def test_constraint_error_automatically_rolls_back_current_frame(self):
        self.engine.begin_transaction()
        with self.assertRaises(ConstraintViolation):
            self.engine.execute_query(parse_cli_command("add {id=1} into users"))
        self.assertEqual(self.engine.transaction_depth, 0)
        self.assertEqual(self.ids(), [1])

    def test_batch_is_atomic_on_failure(self):
        with self.assertRaises(ConstraintViolation):
            self.engine.execute_query(
                {
                    "action": "batch",
                    "queries": [
                        parse_cli_command("add {id=2} into users"),
                        parse_cli_command("add {id=1} into users"),
                    ],
                }
            )
        self.assertEqual(self.ids(), [1])

    def test_transaction_context_manager_and_order_diagnostic(self):
        with self.engine.transaction():
            self.engine.execute_query(parse_cli_command("add {id=2} into users"))
            outer = self.engine.active_transaction_id
            inner = self.engine.begin_transaction()
            with self.assertRaises(EngineError) as raised:
                self.engine.commit_transaction(outer)
            self.assertEqual(raised.exception.code, "transaction_order")
            self.engine.abort_transaction(inner)
        self.assertEqual(self.ids(), [1, 2])


class TransactionSyntaxTests(unittest.TestCase):
    def test_transaction_block_compiles_and_executes_atomically(self):
        query = compile_source(
            """
            transaction{
                create dataset users(table{id(int, pk)})
                add {id=1} into users
                users()
            }
            """
        )
        self.assertEqual(query["action"], "transaction")
        engine = NeoDBEngine()
        result = engine.execute_query(query)
        self.assertEqual(result[-1], [{"id": 1}])
        self.assertEqual(engine.transaction_depth, 0)

    def test_transaction_block_rolls_back_on_constraint_error(self):
        engine = NeoDBEngine()
        query = compile_source(
            """
            transaction{
                create dataset users(table{id(int, pk)})
                add {id=1} into users
                add {id=1} into users
            }
            """
        )
        with self.assertRaises(ConstraintViolation):
            engine.execute_query(query)
        self.assertNotIn("users", engine.datasets)


if __name__ == "__main__":
    unittest.main()
