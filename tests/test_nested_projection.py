import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine import NeoDBEngine
from neoql.errors import EngineError, MissingReferenceError, UnknownFieldError
from neoql.parser import parse_statement, statement_to_query
from neoql.references import ReferenceValue
from neoql.runtime import NeoQLSession
from neoql.selection import ProjectionPlan, Selection


class NestedProjectionTests(unittest.TestCase):
    def setUp(self):
        self.engine = NeoDBEngine()
        self.session = NeoQLSession(self.engine)
        self.session.execute(
            "create dataset users(table{id(int, pk), name(str(20)), profile(json)})"
        )
        self.session.execute(
            "create dataset posts(table{"
            "id(int, pk), author(nullable(users)), "
            "reviewers(set(users)), meta(json)"
            "})"
        )
        self.session.execute(
            'add {id=1, name="Alice", profile={city="Paris", secret="x"}}, '
            '{id=2, name="Ben", profile={city="Rome", secret="y"}} into users'
        )
        self.session.execute(
            "add {id=9, author=1, reviewers=[1, 2], "
            "meta={stats={views=4, hidden=7}, draft=false}}, "
            "{id=10, author=null, reviewers=[], "
            "meta={stats={views=2, hidden=8}, draft=true}} into posts"
        )

    def test_compiler_and_plan_preserve_source_located_projection_tree(self):
        query = statement_to_query(
            parse_statement("posts().(id, author(name, profile(city)))")
        )
        self.assertEqual(query["select"], ["id", "author"])
        author = query["projection"][1]
        self.assertEqual(author["name"], "author")
        self.assertEqual(author["children"][1]["children"][0]["name"], "city")
        self.assertEqual(author["span"].start.column, 14)

        selection = self.engine.execute_query(query)
        self.assertIsInstance(selection, Selection)
        plan = selection.plan[-1]
        self.assertIsInstance(plan, ProjectionPlan)
        self.assertEqual(plan.tree[1].children[1].children[0].name, "city")
        rendered = json.dumps(selection.explain())
        self.assertIn('"line": 1', rendered)

    def test_nested_objects_references_and_collections_do_not_leak_fields(self):
        result = self.session.execute(
            "posts().(id, author(name, profile(city)), "
            "reviewers(name), meta(stats(views))).order(id)"
        ).consume()
        self.assertEqual(
            result,
            [
                {
                    "id": 9,
                    "author": {
                        "name": "Alice",
                        "profile": {"city": "Paris"},
                    },
                    "reviewers": [{"name": "Alice"}, {"name": "Ben"}],
                    "meta": {"stats": {"views": 4}},
                },
                {
                    "id": 10,
                    "author": None,
                    "reviewers": [],
                    "meta": {"stats": {"views": 2}},
                },
            ],
        )

    def test_projection_is_lazy_and_composes_with_filter_and_pagination(self):
        dataset = self.engine.datasets["posts"]
        with patch.object(
            dataset,
            "_selection_records",
            wraps=dataset._selection_records,
        ) as scan:
            selection = self.session.execute(
                "posts({id>=9}).(id, meta(stats(views))).order(id, desc).limit(1)"
            )
            scan.assert_not_called()
            self.assertEqual(
                selection.consume(),
                [{"id": 10, "meta": {"stats": {"views": 2}}}],
            )
            scan.assert_called_once()

    def test_unknown_root_and_nested_fields_are_source_located(self):
        for source in (
            "posts().(missing(name))",
            "posts().(meta(stats(missing)))",
            "posts().(author(missing))",
        ):
            with self.subTest(source=source):
                selection = self.session.execute(source)
                with self.assertRaises(UnknownFieldError) as raised:
                    selection.consume()
                self.assertIsNotNone(raised.exception.span)
                self.assertEqual(raised.exception.code, "unknown_field")

    def test_nested_projection_rejects_scalar_values(self):
        selection = self.session.execute("posts().(id(name))")
        with self.assertRaises(EngineError) as raised:
            selection.consume()
        self.assertEqual(raised.exception.code, "type_mismatch")
        self.assertIsNotNone(raised.exception.span)

    def test_graph_and_kv_values_use_the_same_projection_semantics(self):
        self.session.execute("create dataset pages(document{id(int, pk), body(json)})")
        self.session.execute(
            'add {id=1, body={title="Hello", private=true}} into pages'
        )
        self.session.execute("create dataset people(graph{})")
        self.session.execute(
            'add {id=1, profile={name="Ada", private=true}} into people'
        )
        self.session.execute("create dataset cache(kv{})")
        self.session.execute(
            'add {key="person", value={profile={name="Ada", private=true}}} into cache'
        )
        self.assertEqual(
            self.session.execute("pages().(body(title))").consume(),
            [{"body": {"title": "Hello"}}],
        )
        self.assertEqual(
            self.session.execute("people().(profile(name))").consume(),
            [{"profile": {"name": "Ada"}}],
        )
        self.assertEqual(
            self.session.execute("cache().(value(profile(name)))").consume(),
            [{"value": {"profile": {"name": "Ada"}}}],
        )

    def test_missing_reference_target_is_structured(self):
        self.engine.datasets["posts"].rows[0]["author"] = ReferenceValue(
            "users",
            (("id", 404),),
        )
        selection = self.session.execute("posts({id=9}).(author(name))")
        with self.assertRaises(MissingReferenceError) as raised:
            selection.consume()
        self.assertEqual(raised.exception.details["dataset"], "users")

    def test_reference_expansion_survives_storage_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = Path(directory)
            engine = NeoDBEngine(storage)
            session = NeoQLSession(engine)
            session.execute("create dataset users(table{id(int, pk), profile(json)})")
            session.execute("create dataset posts(table{id(int, pk), author(users)})")
            session.execute('add {id=1, profile={city="Paris", secret=1}} into users')
            session.execute("add {id=2, author=1} into posts")

            reloaded = NeoQLSession(NeoDBEngine(storage))
            self.assertEqual(
                reloaded.execute("posts().(author(profile(city)))").consume(),
                [{"author": {"profile": {"city": "Paris"}}}],
            )


if __name__ == "__main__":
    unittest.main()
