import unittest

from neoql.ast import (
    AddStatement,
    CreateDatasetStatement,
    Logical,
    MethodCall,
    Projection,
    SelectionStatement,
)
from neoql.errors import NeoQLSyntaxError
from neoql.lexer import TokenKind, tokenize
from neoql.parser import parse_statement, statement_to_query


class LexerTests(unittest.TestCase):
    def test_tokenizes_literals_operators_comments_and_multiline_source(self):
        tokens = tokenize(
            """
            # first comment
            users({score>=-4.5 && name!="A\\nB"}) // trailing comment
            """
        )
        self.assertEqual(
            [token.kind for token in tokens],
            [
                TokenKind.IDENTIFIER,
                TokenKind.LEFT_PAREN,
                TokenKind.LEFT_BRACE,
                TokenKind.IDENTIFIER,
                TokenKind.GREATER_EQUAL,
                TokenKind.NUMBER,
                TokenKind.AND,
                TokenKind.IDENTIFIER,
                TokenKind.NOT_EQUAL,
                TokenKind.STRING,
                TokenKind.RIGHT_BRACE,
                TokenKind.RIGHT_PAREN,
                TokenKind.EOF,
            ],
        )
        self.assertEqual(tokens[5].value, -4.5)
        self.assertEqual(tokens[9].value, "A\nB")
        self.assertEqual(tokens[0].span.start.line, 3)

    def test_reports_unexpected_and_unterminated_input(self):
        with self.assertRaisesRegex(NeoQLSyntaxError, "Unexpected character"):
            tokenize("users(@)")
        with self.assertRaisesRegex(NeoQLSyntaxError, "Unterminated string"):
            tokenize('users({name="Alice})')


class ParserASTTests(unittest.TestCase):
    def test_dataset_definition_has_nested_types_constraints_and_spans(self):
        statement = parse_statement(
            """
            create dataset profiles(
                table{
                    id(uuid, pk),
                    tags(list(str(32)), index),
                    settings(map(str, json), default("empty"))
                }
            )
            """
        )
        self.assertIsInstance(statement, CreateDatasetStatement)
        assert isinstance(statement, CreateDatasetStatement)
        self.assertEqual(statement.name, "profiles")
        self.assertEqual(statement.storage, "table")
        self.assertEqual(
            [field.type_ref.render() for field in statement.fields],
            ["uuid", "list(str(32))", "map(str, json)"],
        )
        self.assertEqual(statement.fields[0].constraints[0].name, "pk")
        self.assertEqual(
            statement.fields[2].constraints[0].arguments[0].value,
            "empty",
        )
        self.assertEqual(statement.span.start.line, 2)
        self.assertGreater(statement.span.end.line, statement.span.start.line)

    def test_records_preserve_typed_values(self):
        statement = parse_statement(
            'add {id=1, active=true, note=null, tags=["a", "b"]} into users'
        )
        self.assertIsInstance(statement, AddStatement)
        self.assertEqual(
            statement_to_query(statement)["objects"],
            [{"id": 1, "active": True, "note": None, "tags": ["a", "b"]}],
        )

    def test_predicate_precedence_projection_and_method_chain(self):
        statement = parse_statement(
            """
            users({age>=18 && (verified=true || role="admin")}).
                (name, manager(name, company(city))).
                order(age desc).
                limit(10)
            """
        )
        self.assertIsInstance(statement, SelectionStatement)
        assert isinstance(statement, SelectionStatement)
        self.assertIsInstance(statement.predicate, Logical)
        assert isinstance(statement.predicate, Logical)
        self.assertEqual(statement.predicate.operator, "and")
        self.assertEqual(len(statement.operations), 3)
        projection = statement.operations[0]
        self.assertIsInstance(projection, Projection)
        assert isinstance(projection, Projection)
        self.assertEqual(projection.fields[1].name, "manager")
        self.assertEqual(
            projection.fields[1].children[1].children[0].name,
            "city",
        )
        order = statement.operations[1]
        self.assertIsInstance(order, MethodCall)
        assert isinstance(order, MethodCall)
        self.assertEqual(order.arguments, ("age", "desc"))

    def test_parser_accepts_future_method_calls_without_cli_coupling(self):
        statement = parse_statement("users().future(friends, 2)")
        self.assertIsInstance(statement, SelectionStatement)
        assert isinstance(statement, SelectionStatement)
        self.assertEqual(
            statement.operations[0],
            MethodCall(
                statement.operations[0].span,
                "future",
                ("friends", statement.operations[0].arguments[1]),
            ),
        )

    def test_syntax_error_contains_line_column_and_caret(self):
        source = """
        create dataset users(
            table{id(int, pk), name(str(32)}
        )
        """
        with self.assertRaises(NeoQLSyntaxError) as raised:
            parse_statement(source)
        error = raised.exception
        self.assertEqual(error.line, 3)
        self.assertGreater(error.column, 1)
        rendered = str(error)
        self.assertIn("line 3, column", rendered)
        self.assertIn("^", rendered)


if __name__ == "__main__":
    unittest.main()
