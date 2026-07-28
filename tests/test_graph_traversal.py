import unittest
from unittest.mock import patch

from cli.__main__ import parse_cli_command
from cli.source import split_script
from engine import NeoDBEngine
from neoql.ast import (
    AddLinkStatement,
    RelationshipExpression,
    TraversalOperation,
    WhereOperation,
)
from neoql.errors import InvalidTraversalError, NeoQLSyntaxError, UnknownFieldError
from neoql.parser import parse_statement, statement_to_query
from neoql.selection import Selection, TraversalPlan


class GraphSyntaxTests(unittest.TestCase):
    def test_add_link_and_traversal_compile_to_engine_contract(self):
        statement = parse_statement(
            'add link(label="friend", bidir=true, data={since=2024}) '
            "between users({id=1}), users({id=2})"
        )
        self.assertIsInstance(statement, AddLinkStatement)
        query = statement_to_query(statement)
        self.assertEqual(query["action"], "add_link")
        self.assertEqual(
            query["properties"],
            {"label": "friend", "bidir": True, "data": {"since": 2024}},
        )
        self.assertEqual(query["source"]["filter"]["value"], 1)
        self.assertEqual(query["target"]["filter"]["value"], 2)

        traversal = parse_cli_command("users({id=1}).traverse(friend, 3)")
        self.assertEqual(
            traversal["traverse"],
            {"label": "friend", "depth": 3},
        )

    def test_multiline_link_statement_stays_intact(self):
        statements = split_script(
            """
            add link(
                label="friend",
                bidir=true
            )
            between
            users({id=1}),
            users({id=2})
            users({id=1}).traverse(friend)
            """
        )
        self.assertEqual(len(statements), 2)
        self.assertIsInstance(
            parse_statement(statements[0].source),
            AddLinkStatement,
        )

    def test_relationship_predicate_and_named_depth_have_dedicated_ast(self):
        source = (
            "users({id=1})."
            "traverse(friend({active=true && since>=2024}), depth=3)."
            "where({verified=true})"
        )
        statement = parse_statement(source)
        traversal = statement.operations[0]
        self.assertIsInstance(traversal, TraversalOperation)
        assert isinstance(traversal, TraversalOperation)
        self.assertIsInstance(traversal.relationship, RelationshipExpression)
        self.assertEqual(traversal.relationship.label, "friend")
        self.assertEqual(traversal.depth, 3)
        self.assertEqual(traversal.span.start.column, 15)
        self.assertEqual(traversal.relationship.span.start.column, 24)
        self.assertIsInstance(statement.operations[1], WhereOperation)

        query = statement_to_query(statement)
        self.assertEqual(
            query["traverse"],
            {
                "label": "friend",
                "depth": 3,
                "predicate": {
                    "and": [
                        {"field": "active", "op": "=", "value": True},
                        {"field": "since", "op": ">=", "value": 2024},
                    ]
                },
            },
        )
        self.assertEqual(query["pipeline"][1]["operation"], "where")

    def test_invalid_named_depth_is_source_located(self):
        for source in (
            "users().traverse(friend(), depth=0)",
            "users().traverse(friend(), depth=true)",
            "users().traverse(friend(), depth=1.5)",
        ):
            with (
                self.subTest(source=source),
                self.assertRaises(NeoQLSyntaxError) as raised,
            ):
                parse_statement(source)
            self.assertIsNotNone(raised.exception.span)


class GraphTraversalTests(unittest.TestCase):
    def setUp(self):
        self.engine = NeoDBEngine()
        self.engine.execute_query(parse_cli_command("create dataset users(graph)"))
        self.engine.execute_query(
            parse_cli_command(
                'add {id=1, name="A", active=true}, '
                '{id=2, name="B", active=false}, '
                '{id=3, name="C", active=true}, '
                '{id=4, name="D", active=true} into users'
            )
        )

    def add_link(
        self,
        source,
        target,
        *,
        label="friend",
        bidir=False,
        data=None,
    ):
        rendered_data = ""
        if data:
            fields = ", ".join(
                f"{key}={str(value).lower() if isinstance(value, bool) else value}"
                for key, value in data.items()
            )
            rendered_data = f", data={{{fields}}}"
        return self.engine.execute_query(
            parse_cli_command(
                f"add link(label={label}, bidir={'true' if bidir else 'false'}"
                f"{rendered_data}) "
                f"between users({{id={source}}}), users({{id={target}}})"
            )
        )

    def traverse(self, source, *, label="friend", depth=1):
        return self.engine.execute_query(
            parse_cli_command(f"users({{id={source}}}).traverse({label}, {depth})")
        )

    def test_directed_and_bidirectional_links(self):
        link = self.add_link(1, 2)
        self.assertEqual(link["link"]["source"], 1)
        self.assertFalse(link["link"]["bidir"])
        self.assertEqual([row["id"] for row in self.traverse(1)], [2])
        self.assertEqual(self.traverse(2).consume(), [])

        self.add_link(2, 3, bidir=True)
        self.assertEqual([row["id"] for row in self.traverse(3)], [2])

    def test_depth_cycles_labels_and_post_traversal_filters(self):
        self.add_link(1, 2)
        self.add_link(2, 3)
        self.add_link(3, 1)
        self.add_link(1, 4, label="coworker")

        selection = self.traverse(1, depth=5)
        self.assertIsInstance(selection, Selection)
        self.assertIsInstance(selection.plan[-1], TraversalPlan)
        self.assertEqual([row["id"] for row in selection], [2, 3])
        self.assertEqual(
            [
                row["id"]
                for row in selection.where(
                    {"field": "active", "op": "=", "value": True}
                )
            ],
            [3],
        )
        self.assertEqual(
            [row["id"] for row in self.traverse(1, label="coworker")],
            [4],
        )

    def test_missing_ambiguous_and_non_graph_paths_are_structured(self):
        with self.assertRaises(InvalidTraversalError):
            self.add_link(1, 99)
        with self.assertRaises(InvalidTraversalError):
            self.engine.execute_query(
                parse_cli_command(
                    "add link(label=friend) between users(), users({id=2})"
                )
            )

        self.engine.execute_query(
            parse_cli_command("create dataset table_users(table{id(int, pk)})")
        )
        self.engine.execute_query(parse_cli_command("add {id=1} into table_users"))
        with self.assertRaises(InvalidTraversalError) as raised:
            self.engine.execute_query(
                parse_cli_command("table_users({id=1}).traverse(friend)")
            ).consume()
        self.assertEqual(raised.exception.code, "invalid_traversal")

    def test_link_predicate_is_separate_from_target_node_filter(self):
        self.add_link(1, 2, data={"active": False, "since": 2020})
        self.add_link(1, 3, data={"active": True, "since": 2024})
        self.add_link(3, 4, data={"active": True, "since": 2025})

        selection = self.engine.execute_query(
            parse_cli_command(
                "users({id=1})."
                "traverse(friend({active=true && since>=2024}), depth=2)"
                ".where({active=true})"
            )
        )
        self.assertEqual([row["id"] for row in selection], [3, 4])

        node_filtered = self.engine.execute_query(
            parse_cli_command(
                "users({id=1}).traverse(friend({active=false}), depth=1)"
                ".where({active=true})"
            )
        )
        self.assertEqual(node_filtered.consume(), [])

        explained = self.engine.execute_query(
            parse_cli_command(
                "users({id=1}).traverse(friend({active=true}), depth=2).explain()"
            )
        )
        traversal_plan = explained["logical"][-1]
        self.assertEqual(traversal_plan["node"], "TraversalPlan")
        self.assertEqual(
            traversal_plan["predicate"],
            {"field": "active", "op": "=", "value": True},
        )

    def test_filtered_bidirectional_cycles_are_lazy_and_bounded(self):
        self.add_link(1, 2, bidir=True, data={"enabled": True})
        self.add_link(2, 3, bidir=True, data={"enabled": True})
        self.add_link(3, 1, bidir=True, data={"enabled": True})
        graph = self.engine.datasets["users"]
        with patch.object(
            graph,
            "_traverse_selection",
            wraps=graph._traverse_selection,
        ) as traversal:
            selection = self.engine.execute_query(
                parse_cli_command(
                    "users({id=3}).traverse(friend({enabled=true}), depth=10)"
                )
            )
            traversal.assert_not_called()
            self.assertEqual([row["id"] for row in selection], [2, 1])
            traversal.assert_called_once()

    def test_unknown_relationship_fields_and_dataset_context_are_structured(self):
        self.add_link(1, 2, data={"since": 2024})
        with self.assertRaises(UnknownFieldError) as field:
            self.engine.execute_query(
                parse_cli_command("users({id=1}).traverse(friend({missing=true}))")
            ).consume()
        self.assertEqual(field.exception.details["dataset"], "users.friend")

        self.engine.execute_query(parse_cli_command("create dataset teams(graph)"))
        self.engine.execute_query(parse_cli_command("add {id=1} into teams"))
        users = self.engine.execute_query(parse_cli_command("users({id=1})"))
        teams = self.engine.execute_query(parse_cli_command("teams({id=1})"))
        with self.assertRaises(InvalidTraversalError):
            users.union(teams).traverse("friend")


if __name__ == "__main__":
    unittest.main()
