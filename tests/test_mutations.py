import unittest

from cli.__main__ import parse_cli_command
from engine import NeoDBEngine
from neoql.ast import DeleteStatement, UpdateStatement
from neoql.errors import NeoQLSyntaxError, ReferenceInUseError
from neoql.parser import parse_statement, statement_to_query
from neoql.schema import ConstraintViolation


class MutationParserTests(unittest.TestCase):
    def test_update_and_delete_have_source_located_ast_nodes(self):
        source = '\nusers({id=1}).update({name="Alice", profile={active=true}})'
        update = parse_statement(source)
        self.assertIsInstance(update, UpdateStatement)
        assert isinstance(update, UpdateStatement)
        self.assertEqual(update.span.start.line, 2)
        self.assertEqual(update.span.end.offset, len(source))
        self.assertEqual(
            statement_to_query(update),
            {
                "action": "update",
                "dataset": "users",
                "filter": {"field": "id", "op": "=", "value": 1},
                "values": {
                    "name": "Alice",
                    "profile": {"active": True},
                },
            },
        )

        delete = parse_statement("users({inactive=true}).delete()")
        self.assertIsInstance(delete, DeleteStatement)
        self.assertEqual(
            statement_to_query(delete),
            {
                "action": "delete",
                "dataset": "users",
                "filter": {
                    "field": "inactive",
                    "op": "=",
                    "value": True,
                },
            },
        )

    def test_mutations_are_terminal_and_validate_arguments(self):
        invalid = [
            "users().limit(1).delete()",
            "users().delete({id=1})",
            "users().update({})",
            "users().update({name='A'}).limit(1)",
        ]
        for source in invalid:
            with self.subTest(source=source), self.assertRaises(NeoQLSyntaxError):
                parse_statement(source)


class MutationEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = NeoDBEngine()
        self.engine.execute_query(
            parse_cli_command(
                "create dataset users("
                "table{id(int, pk, readonly), email(str(100), unique), age(int)}"
                ")"
            )
        )
        self.engine.execute_query(
            parse_cli_command(
                'add {id=1, email="a@example.com", age=20}, '
                '{id=2, email="b@example.com", age=30} into users'
            )
        )

    def rows(self):
        return list(self.engine.execute_query(parse_cli_command("users()")))

    def test_filtered_update_and_delete_report_affected_counts(self):
        updated = self.engine.execute_query(
            parse_cli_command("users({id=1}).update({age=21})")
        )
        self.assertEqual(updated, {"status": "success", "updated": 1})
        self.assertEqual(self.rows()[0]["age"], 21)

        deleted = self.engine.execute_query(
            parse_cli_command("users({age>=30}).delete()")
        )
        self.assertEqual(deleted, {"status": "success", "deleted": 1})
        self.assertEqual([row["id"] for row in self.rows()], [1])

    def test_empty_and_full_dataset_mutations_are_defined(self):
        self.assertEqual(
            self.engine.execute_query(
                parse_cli_command("users({id=99}).update({age=40})")
            ),
            {"status": "success", "updated": 0},
        )
        self.assertEqual(
            self.engine.execute_query(parse_cli_command("users({id=99}).delete()")),
            {"status": "success", "deleted": 0},
        )
        self.assertEqual(
            self.engine.execute_query(parse_cli_command("users().delete()")),
            {"status": "success", "deleted": 2},
        )
        self.assertEqual(self.rows(), [])

    def test_schema_failures_leave_records_unchanged(self):
        invalid = [
            ("users({id=1}).update({id=3})", "readonly"),
            ('users().update({email="same@example.com"})', "unique"),
            ("users({id=1}).update({missing=3})", "unknown_field"),
        ]
        for source, code in invalid:
            before = self.rows()
            with (
                self.subTest(source=source),
                self.assertRaises(ConstraintViolation) as raised,
            ):
                self.engine.execute_query(parse_cli_command(source))
            self.assertEqual(raised.exception.code, code)
            self.assertEqual(self.rows(), before)

    def test_reference_resolution_and_source_update_are_one_transaction(self):
        engine = NeoDBEngine()
        engine.execute_query(
            parse_cli_command(
                "create dataset managers(table{id(int, pk), name(str(100))})"
            )
        )
        engine.execute_query(
            parse_cli_command(
                "create dataset users("
                "table{id(int, pk), email(str(100), unique), "
                "manager(managers)}"
                ")"
            )
        )
        engine.execute_query(
            parse_cli_command(
                'add {id=1, email="a", manager={id=1, name="One"}}, '
                '{id=2, email="b", manager=1} into users'
            )
        )

        with self.assertRaises(ConstraintViolation):
            engine.execute_query(
                parse_cli_command(
                    'users().update({email="same", manager={id=2, name="Two"}})'
                )
            )
        managers = list(engine.execute_query(parse_cli_command("managers()")))
        self.assertEqual(managers, [{"id": 1, "name": "One"}])

    def test_referenced_identity_cannot_be_changed_or_deleted(self):
        engine = NeoDBEngine()
        engine.execute_query(
            parse_cli_command(
                "create dataset managers(table{id(int, pk), name(str(100))})"
            )
        )
        engine.execute_query(
            parse_cli_command(
                "create dataset users(table{id(int, pk), manager(managers)})"
            )
        )
        engine.execute_query(parse_cli_command('add {id=1, name="One"} into managers'))
        engine.execute_query(parse_cli_command("add {id=1, manager=1} into users"))

        for source in [
            "managers({id=1}).update({id=2})",
            "managers({id=1}).delete()",
        ]:
            with (
                self.subTest(source=source),
                self.assertRaises(ReferenceInUseError) as raised,
            ):
                engine.execute_query(parse_cli_command(source))
            self.assertEqual(raised.exception.code, "reference_in_use")
        self.assertEqual(
            list(engine.execute_query(parse_cli_command("managers()"))),
            [{"id": 1, "name": "One"}],
        )


if __name__ == "__main__":
    unittest.main()
