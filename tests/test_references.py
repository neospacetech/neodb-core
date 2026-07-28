import unittest

from cli.__main__ import parse_cli_command
from engine import NeoDBEngine
from neoql.errors import (
    AmbiguousReferenceError,
    DatasetNotFoundError,
    MissingReferenceError,
    ReferenceConflictError,
    ReferenceCycleError,
)
from neoql.references import ReferenceValue
from neoql.schema import ConstraintViolation


class ReferenceTestCase(unittest.TestCase):
    def execute(self, source):
        return self.engine.execute_query(parse_cli_command(source))

    def setUp(self):
        self.engine = NeoDBEngine()
        self.execute(
            "create dataset users(table{"
            "id(int, pk), email(str(50), unique), name(str(30))"
            "})"
        )


class TableReferenceTests(ReferenceTestCase):
    def setUp(self):
        super().setUp()
        self.execute(
            "create dataset posts(table{id(int, pk), author(users), title(str(50))})"
        )

    def test_inline_object_is_inserted_and_stored_as_typed_reference(self):
        self.execute(
            'add {id=1, author={id=7, email="a@x", name="Alice"}, '
            'title="Hello"} into posts'
        )
        self.assertEqual(
            self.engine.datasets["users"].rows,
            [{"id": 7, "email": "a@x", "name": "Alice"}],
        )
        reference = self.engine.datasets["posts"].rows[0]["author"]
        self.assertEqual(reference, ReferenceValue("users", (("id", 7),)))
        self.assertEqual(reference.to_dict()["$ref"], "users")

    def test_existing_identity_is_reused_without_duplicate_insert(self):
        self.execute('add {id=7, email="a@x", name="Alice"} into users')
        self.execute(
            'add {id=1, author={id=7, email="a@x", name="Alice"}, '
            'title="One"} into posts'
        )
        self.execute('add {id=2, author={email="a@x"}, title="Two"} into posts')
        self.assertEqual(len(self.engine.datasets["users"].rows), 1)
        self.assertEqual(
            self.engine.datasets["posts"].rows[0]["author"],
            self.engine.datasets["posts"].rows[1]["author"],
        )

    def test_scalar_and_explicit_reference_values_are_validated(self):
        self.execute('add {id=7, email="a@x", name="Alice"} into users')
        self.execute('add {id=1, author=7, title="One"} into posts')
        self.engine.execute_query(
            {
                "action": "insert",
                "dataset": "posts",
                "objects": [
                    {
                        "id": 2,
                        "author": ReferenceValue("users", (("id", "7"),)),
                        "title": "Two",
                    }
                ],
            }
        )
        self.assertEqual(
            self.engine.datasets["posts"].rows[1]["author"],
            ReferenceValue("users", (("id", 7),)),
        )
        with self.assertRaises(MissingReferenceError):
            self.execute('add {id=3, author=99, title="Missing"} into posts')

    def test_conflicting_and_ambiguous_identity_are_structured(self):
        self.execute('add {id=1, email="one@x", name="One"} into users')
        self.execute('add {id=2, email="two@x", name="Two"} into users')
        with self.assertRaises(ReferenceConflictError):
            self.execute(
                'add {id=1, author={id=1, name="Changed"}, title="Conflict"} into posts'
            )
        with self.assertRaises(AmbiguousReferenceError):
            self.execute(
                'add {id=2, author={id=1, email="two@x"}, title="Ambiguous"} into posts'
            )

    def test_inline_insert_rolls_back_when_source_record_fails(self):
        with self.assertRaises(ConstraintViolation):
            self.execute(
                'add {id=1, author={id=7, email="a@x", name="Alice"}} into posts'
            )
        self.assertEqual(self.engine.datasets["users"].rows, [])
        self.assertEqual(self.engine.datasets["posts"].rows, [])


class CollectionAndGraphReferenceTests(ReferenceTestCase):
    def test_reference_collections_resolve_inline_and_existing_records(self):
        self.execute(
            "create dataset teams(table{"
            "id(int, pk), members(list(users)), reviewers(set(users))"
            "})"
        )
        self.execute('add {id=1, email="one@x", name="One"} into users')
        self.execute(
            'add {id=1, members=[1, {id=2, email="two@x", name="Two"}], '
            "reviewers=[1, 2]} into teams"
        )
        team = self.engine.datasets["teams"].rows[0]
        self.assertEqual(
            team["members"],
            [
                ReferenceValue("users", (("id", 1),)),
                ReferenceValue("users", (("id", 2),)),
            ],
        )
        self.assertEqual(
            team["reviewers"],
            {
                ReferenceValue("users", (("id", 1),)),
                ReferenceValue("users", (("id", 2),)),
            },
        )

    def test_graph_targets_support_existing_and_inline_nodes(self):
        self.execute("create dataset people(graph{})")
        self.execute('add {id=1, name="Alice"} into people')
        self.execute("create dataset events(table{id(int, pk), attendee(people)})")
        self.execute("add {id=1, attendee=1} into events")
        self.execute('add {id=2, attendee={id=2, name="Ben"}} into events')
        self.assertEqual(set(self.engine.datasets["people"].nodes), {1, 2})
        self.assertEqual(
            self.engine.datasets["events"].rows[1]["attendee"],
            ReferenceValue("people", (("id", 2),)),
        )


class ReferenceSchemaAndCycleTests(ReferenceTestCase):
    def test_unknown_or_identityless_targets_are_rejected(self):
        with self.assertRaises(DatasetNotFoundError):
            self.execute("create dataset broken(table{id(int, pk), owner(missing)})")
        self.execute("create dataset logs(table{message(str(20))})")
        with self.assertRaises(AmbiguousReferenceError):
            self.execute("create dataset broken(table{id(int, pk), log(logs)})")

    def test_self_reference_cycle_is_detected_and_rolled_back(self):
        self.execute(
            "create dataset employees(table{id(int, pk), manager(nullable(employees))})"
        )
        employee = {"id": 1}
        employee["manager"] = employee
        with self.assertRaises(ReferenceCycleError):
            self.engine.execute_query(
                {
                    "action": "insert",
                    "dataset": "employees",
                    "objects": [employee],
                }
            )
        self.assertEqual(self.engine.datasets["employees"].rows, [])


if __name__ == "__main__":
    unittest.main()
