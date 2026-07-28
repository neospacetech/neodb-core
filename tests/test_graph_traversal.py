import unittest

from cli.__main__ import parse_cli_command
from cli.source import split_script
from engine import NeoDBEngine
from neoql.ast import AddLinkStatement
from neoql.errors import InvalidTraversalError
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

    def add_link(self, source, target, *, label="friend", bidir=False):
        return self.engine.execute_query(
            parse_cli_command(
                f"add link(label={label}, bidir={'true' if bidir else 'false'}) "
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


if __name__ == "__main__":
    unittest.main()
