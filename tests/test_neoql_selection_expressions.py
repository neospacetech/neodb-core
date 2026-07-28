import unittest
from unittest.mock import patch

from engine import NeoDBEngine
from neoql.ast import (
    AlgebraExpression,
    SelectionPipelineExpression,
    VariableReferenceStatement,
)
from neoql.errors import EngineError, NeoQLSyntaxError, UnknownNameError
from neoql.lexer import TokenKind, tokenize
from neoql.parser import parse_statement, statement_to_query
from neoql.runtime import NeoQLSession
from neoql.selection import Selection


class SelectionExpressionParserTests(unittest.TestCase):
    def test_lexer_and_parser_define_algebra_precedence(self):
        tokens = tokenize("A + B & C - D ^ E * F")
        self.assertEqual(
            [token.kind for token in tokens if token.kind is not TokenKind.IDENTIFIER],
            [
                TokenKind.PLUS,
                TokenKind.AMPERSAND,
                TokenKind.MINUS,
                TokenKind.CARET,
                TokenKind.STAR,
                TokenKind.EOF,
            ],
        )

        expression = parse_statement("A + B & C")
        self.assertIsInstance(expression, AlgebraExpression)
        assert isinstance(expression, AlgebraExpression)
        self.assertEqual(expression.operator, "union")
        self.assertIsInstance(expression.left, VariableReferenceStatement)
        self.assertIsInstance(expression.right, AlgebraExpression)
        assert isinstance(expression.right, AlgebraExpression)
        self.assertEqual(expression.right.operator, "intersection")

        grouped = parse_statement("(A + B).limit(1)")
        self.assertIsInstance(grouped, SelectionPipelineExpression)
        assert isinstance(grouped, SelectionPipelineExpression)
        self.assertIsInstance(grouped.base, AlgebraExpression)
        self.assertEqual(grouped.span.start.column, 1)
        self.assertEqual(grouped.span.end.column, 17)

    def test_extended_methods_compile_to_ordered_pipeline(self):
        statement = parse_statement(
            "users().where({active=true}).unique(id).sort(id).reverse().limit(2)"
        )
        query = statement_to_query(statement)
        self.assertEqual(
            query["pipeline"],
            [
                {
                    "operation": "where",
                    "predicate": {
                        "field": "active",
                        "op": "=",
                        "value": True,
                    },
                },
                {"operation": "unique", "fields": ["id"]},
                {
                    "operation": "order",
                    "fields": ["id"],
                    "direction": "asc",
                },
                {"operation": "reverse"},
                {"operation": "limit", "count": 2},
            ],
        )

    def test_extended_method_arity_errors_are_source_located(self):
        invalid = [
            "users().sort()",
            "users().reverse(id)",
            "users().flatten()",
            "users().expand(a, b)",
            "users().unique(1)",
        ]
        for source in invalid:
            with (
                self.subTest(source=source),
                self.assertRaises(NeoQLSyntaxError) as raised,
            ):
                statement_to_query(parse_statement(source))
            self.assertIsNotNone(raised.exception.span)


class SelectionExpressionRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.engine = NeoDBEngine()
        self.session = NeoQLSession(self.engine)
        self.session.execute(
            "create dataset users("
            "table{id(int), active(bool), tags(list(str(10))), profile(json)}"
            ")"
        )
        self.session.execute(
            'add {id=1, active=true, tags=["a", "b"], profile={name="A"}}, '
            '{id=2, active=true, tags=["a"], profile={name="B"}}, '
            '{id=2, active=true, tags=["a"], profile={name="B"}}, '
            '{id=3, active=false, tags=[], profile={name="C"}} into users'
        )

    def test_unary_methods_preserve_source_order_and_laziness(self):
        dataset = self.engine.datasets["users"]
        with patch.object(
            dataset,
            "_selection_records",
            wraps=dataset._selection_records,
        ) as scan:
            selection = self.session.execute(
                "users().limit(3).unique(id).sort(id).reverse().limit(2)"
            )
            self.assertIsInstance(selection, Selection)
            scan.assert_not_called()
            self.assertEqual([row["id"] for row in selection.consume()], [2, 1])
            scan.assert_called_once()

    def test_where_flatten_expand_and_distinct_are_composable(self):
        result = self.session.execute(
            "users().where({active=true}).distinct(id)."
            "flatten(tags).expand(profile).sort(id)"
        ).consume()
        self.assertEqual(
            result,
            [
                {"id": 1, "active": True, "tags": "a", "name": "A"},
                {"id": 1, "active": True, "tags": "b", "name": "A"},
                {"id": 2, "active": True, "tags": "a", "name": "B"},
            ],
        )

    def test_all_algebra_operators_are_lazy_and_parentheses_chain(self):
        self.session.execute("A = users({id<=2}).distinct(id)")
        self.session.execute("B = users({id>=2}).distinct(id)")
        self.session.execute("C = A + B")
        self.session.execute("function overlap(){ A & B }")

        dataset = self.engine.datasets["users"]
        with patch.object(
            dataset,
            "_selection_records",
            wraps=dataset._selection_records,
        ) as scan:
            union = self.session.execute("A + B")
            scan.assert_not_called()
            self.assertEqual(
                [row["id"] for row in union.consume()],
                [1, 2, 3],
            )
            self.assertEqual(
                [row["id"] for row in self.session.execute("C").consume()],
                [1, 2, 3],
            )
            self.assertEqual(
                [row["id"] for row in self.session.execute("overlap()").consume()],
                [2],
            )
            self.assertEqual(
                [row["id"] for row in self.session.execute("A - B").consume()],
                [1],
            )
            self.assertEqual(
                [
                    row["id"]
                    for row in self.session.execute("(A ^ B).sort(id)").consume()
                ],
                [1, 3],
            )
            product = self.session.execute("A * B").limit(1).consume()
            self.assertEqual(product[0]["left"]["id"], 1)
            self.assertEqual(product[0]["right"]["id"], 2)

    def test_operand_and_schema_errors_retain_expression_location(self):
        with self.assertRaises(UnknownNameError) as unknown:
            self.session.execute("missing + users()")
        self.assertEqual(unknown.exception.span.start.column, 1)

        self.session.execute("create dataset names(table{name(str(10))})")
        self.session.execute('add {name="A"} into names')
        self.session.execute("ids = users().(id)")
        self.session.execute("namesOnly = names()")
        with self.assertRaises(EngineError) as mismatch:
            self.session.execute("\nids + namesOnly").consume()
        self.assertEqual(mismatch.exception.code, "schema_mismatch")
        self.assertEqual(mismatch.exception.span.start.line, 2)


if __name__ == "__main__":
    unittest.main()
