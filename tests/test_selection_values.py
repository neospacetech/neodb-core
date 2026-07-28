import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli.__main__ import parse_cli_command
from engine import NeoDBEngine
from neoql.ast import AddSelectionStatement, SelectionValue
from neoql.errors import (
    AmbiguousReferenceError,
    MissingReferenceError,
    ReferenceConflictError,
)
from neoql.parser import parse_statement, statement_to_query
from neoql.references import ReferenceValue, SelectionQueryValue
from neoql.runtime import NeoQLSession
from neoql.schema import ConstraintViolation


class SelectionValueParserTests(unittest.TestCase):
    def test_selection_insert_and_field_values_keep_source_locations(self):
        insertion = parse_statement("\nadd users({active=true}) into archive")
        self.assertIsInstance(insertion, AddSelectionStatement)
        assert isinstance(insertion, AddSelectionStatement)
        self.assertEqual(insertion.span.start.line, 2)
        self.assertEqual(insertion.source.span.start.column, 5)

        record = parse_statement("add {owner=users({id=1})} into projects")
        value = record.records[0].fields[0].value
        self.assertIsInstance(value, SelectionValue)
        self.assertEqual(value.span.start.column, 12)

    def test_direct_selection_values_compile_to_lazy_query_markers(self):
        insertion = statement_to_query(
            parse_statement("add users({active=true}) into archive")
        )
        self.assertEqual(insertion["action"], "insert_selection")
        self.assertEqual(insertion["source"]["dataset"], "users")

        record = statement_to_query(
            parse_statement("add {owner=users({id=1})} into projects")
        )
        self.assertIsInstance(record["objects"][0]["owner"], SelectionQueryValue)


class SelectionInsertionTests(unittest.TestCase):
    def setUp(self):
        self.engine = NeoDBEngine()
        self.session = NeoQLSession(self.engine)
        self.session.execute(
            "create dataset users(table{id(int), name(str(20)), active(bool)})"
        )
        self.session.execute(
            'add {id=1, name="A", active=true}, '
            '{id=2, name="B", active=false} into users'
        )
        self.session.execute(
            "create dataset archive(table{id(int), name(str(20)), active(bool)})"
        )

    def test_direct_engine_and_empty_selection_insert(self):
        result = self.engine.execute_query(
            parse_cli_command("add users({active=true}) into archive")
        )
        self.assertEqual(result, {"status": "success", "inserted": 1})
        self.assertEqual(self.engine.datasets["archive"].rows[0]["id"], 1)

        result = self.session.execute("add users({id=99}) into archive")
        self.assertEqual(result, {"status": "success", "inserted": 0})

    def test_bound_and_algebra_sources_stay_lazy_until_insert(self):
        dataset = self.engine.datasets["users"]
        with patch.object(
            dataset,
            "_selection_records",
            wraps=dataset._selection_records,
        ) as scan:
            self.session.execute("activeUsers = users({active=true})")
            scan.assert_not_called()
            result = self.session.execute("add activeUsers into archive")
            self.assertEqual(result["inserted"], 1)
            scan.assert_called_once()

        self.session.execute("inactiveUsers = users({active=false})")
        result = self.session.execute(
            "add (activeUsers + inactiveUsers).sort(id) into archive"
        )
        self.assertEqual(result["inserted"], 2)

    def test_source_is_snapshotted_before_self_insert(self):
        result = self.session.execute("add users() into users")
        self.assertEqual(result["inserted"], 2)
        self.assertEqual(len(self.engine.datasets["users"].rows), 4)

    def test_self_insert_constraint_failure_is_atomic(self):
        self.session.execute(
            "create dataset keyed(table{id(int, pk), name(str(20))})"
        )
        self.session.execute('add {id=1, name="A"} into keyed')
        with self.assertRaises(ConstraintViolation):
            self.session.execute("add keyed() into keyed")
        self.assertEqual(
            self.engine.datasets["keyed"].rows,
            [{"id": 1, "name": "A"}],
        )

    def test_destination_schema_failure_rolls_back_every_source_record(self):
        self.session.execute("create dataset ids(table{id(int)})")
        with self.assertRaises(ConstraintViolation):
            self.session.execute("add users() into ids")
        self.assertEqual(self.engine.datasets["ids"].rows, [])

    def test_committed_selection_insert_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            engine = NeoDBEngine(path)
            session = NeoQLSession(engine)
            session.execute("create dataset source(table{id(int, pk)})")
            session.execute("create dataset target(table{id(int, pk)})")
            session.execute("add {id=1}, {id=2} into source")
            session.execute("add source() into target")

            restarted = NeoDBEngine(path)
            self.assertEqual(
                restarted.datasets["target"].rows,
                [{"id": 1}, {"id": 2}],
            )


class SelectionReferenceTests(unittest.TestCase):
    def setUp(self):
        self.engine = NeoDBEngine()
        self.session = NeoQLSession(self.engine)
        self.session.execute(
            "create dataset users(table{id(int, pk), name(str(20))})"
        )
        self.session.execute('add {id=1, name="A"}, {id=2, name="B"} into users')
        self.session.execute(
            "create dataset projects("
            "table{id(int, pk), owner(users), members(list(users))}"
            ")"
        )

    def test_scalar_selection_requires_exactly_one_record(self):
        self.session.execute(
            "add {id=1, owner=users({id=1}), members=[]} into projects"
        )
        self.assertEqual(
            self.engine.datasets["projects"].rows[0]["owner"],
            ReferenceValue("users", (("id", 1),)),
        )

        with self.assertRaises(MissingReferenceError):
            self.session.execute(
                "add {id=2, owner=users({id=99}), members=[]} into projects"
            )
        with self.assertRaises(AmbiguousReferenceError):
            self.session.execute(
                "add {id=2, owner=users(), members=[]} into projects"
            )
        self.assertEqual(len(self.engine.datasets["projects"].rows), 1)

    def test_collection_selection_expands_in_stable_order(self):
        self.session.execute(
            "selected = users().sort(id)"
        )
        self.session.execute(
            "add {id=1, owner=users({id=1}), members=(selected)} into projects"
        )
        members = self.engine.datasets["projects"].rows[0]["members"]
        self.assertEqual(
            members,
            [
                ReferenceValue("users", (("id", 1),)),
                ReferenceValue("users", (("id", 2),)),
            ],
        )

    def test_selection_origin_must_match_reference_target(self):
        self.session.execute("create dataset teams(table{id(int, pk)})")
        self.session.execute("add {id=1} into teams")
        with self.assertRaises(ReferenceConflictError):
            self.session.execute(
                "add {id=1, owner=teams({id=1}), members=[]} into projects"
            )
        self.assertEqual(self.engine.datasets["projects"].rows, [])

    def test_reference_resolution_and_destination_validation_share_transaction(self):
        with self.assertRaises(ConstraintViolation):
            self.session.execute(
                "add {id=1, owner=users({id=1}), members=users()}, "
                "{id=1, owner=users({id=2}), members=[]} into projects"
            )
        self.assertEqual(self.engine.datasets["projects"].rows, [])


if __name__ == "__main__":
    unittest.main()
