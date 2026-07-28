"""NeoQL lexer."""

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .ast import Position, Span
from .errors import NeoQLSyntaxError


class TokenKind(str, Enum):
    IDENTIFIER = "identifier"
    NUMBER = "number"
    STRING = "string"
    LEFT_PAREN = "("
    RIGHT_PAREN = ")"
    LEFT_BRACE = "{"
    RIGHT_BRACE = "}"
    LEFT_BRACKET = "["
    RIGHT_BRACKET = "]"
    COMMA = ","
    DOT = "."
    EQUAL = "="
    NOT_EQUAL = "!="
    GREATER = ">"
    GREATER_EQUAL = ">="
    LESS = "<"
    LESS_EQUAL = "<="
    AND = "&&"
    OR = "||"
    NOT = "!"
    EOF = "eof"


@dataclass(frozen=True, slots=True)
class Token:
    kind: TokenKind
    lexeme: str
    value: Any
    span: Span


class Lexer:
    """Turn NeoQL source text into located tokens."""

    def __init__(self, source: str):
        self.source = source
        self.offset = 0
        self.line = 1
        self.column = 1

    def tokenize(self) -> tuple[Token, ...]:
        tokens = []
        while not self._at_end():
            self._skip_trivia()
            if self._at_end():
                break
            tokens.append(self._scan_token())
        position = self._position()
        tokens.append(Token(TokenKind.EOF, "", None, Span(position, position)))
        return tuple(tokens)

    def _scan_token(self) -> Token:
        start = self._position()
        char = self._advance()
        punctuation = {
            "(": TokenKind.LEFT_PAREN,
            ")": TokenKind.RIGHT_PAREN,
            "{": TokenKind.LEFT_BRACE,
            "}": TokenKind.RIGHT_BRACE,
            "[": TokenKind.LEFT_BRACKET,
            "]": TokenKind.RIGHT_BRACKET,
            ",": TokenKind.COMMA,
            ".": TokenKind.DOT,
            "=": TokenKind.EQUAL,
        }
        if char in punctuation:
            return self._token(punctuation[char], start)
        if char == "!":
            return self._token(
                TokenKind.NOT_EQUAL if self._match("=") else TokenKind.NOT, start
            )
        if char == ">":
            return self._token(
                TokenKind.GREATER_EQUAL if self._match("=") else TokenKind.GREATER,
                start,
            )
        if char == "<":
            return self._token(
                TokenKind.LESS_EQUAL if self._match("=") else TokenKind.LESS,
                start,
            )
        if char == "&" and self._match("&"):
            return self._token(TokenKind.AND, start)
        if char == "|" and self._match("|"):
            return self._token(TokenKind.OR, start)
        if char in "\"'":
            return self._string(char, start)
        if char.isdigit() or (char == "-" and self._peek().isdigit()):
            return self._number(start)
        if char.isalpha() or char == "_":
            return self._identifier(start)
        raise NeoQLSyntaxError(
            f"Unexpected character {char!r}",
            Span(start, self._position()),
            self.source,
        )

    def _skip_trivia(self) -> None:
        while not self._at_end():
            if self._peek().isspace():
                self._advance()
            elif self._peek() == "#":
                self._skip_line()
            elif self._peek() == "/" and self._peek_next() == "/":
                self._advance()
                self._advance()
                self._skip_line()
            else:
                return

    def _skip_line(self) -> None:
        while not self._at_end() and self._peek() != "\n":
            self._advance()

    def _string(self, quote: str, start: Position) -> Token:
        value = []
        escapes = {"n": "\n", "r": "\r", "t": "\t", "\\": "\\", quote: quote}
        while not self._at_end() and self._peek() != quote:
            char = self._advance()
            if char == "\\":
                if self._at_end():
                    break
                escaped = self._advance()
                value.append(escapes.get(escaped, escaped))
            else:
                value.append(char)
        if self._at_end():
            raise NeoQLSyntaxError(
                "Unterminated string literal",
                Span(start, self._position()),
                self.source,
            )
        self._advance()
        return self._token(TokenKind.STRING, start, "".join(value))

    def _number(self, start: Position) -> Token:
        while self._peek().isdigit():
            self._advance()
        if self._peek() == "." and self._peek_next().isdigit():
            self._advance()
            while self._peek().isdigit():
                self._advance()
        lexeme = self.source[start.offset : self.offset]
        value: int | float = float(lexeme) if "." in lexeme else int(lexeme)
        return self._token(TokenKind.NUMBER, start, value)

    def _identifier(self, start: Position) -> Token:
        while self._peek().isalnum() or self._peek() == "_":
            self._advance()
        lexeme = self.source[start.offset : self.offset]
        return self._token(TokenKind.IDENTIFIER, start, lexeme)

    def _token(self, kind: TokenKind, start: Position, value: Any = None) -> Token:
        lexeme = self.source[start.offset : self.offset]
        return Token(kind, lexeme, value, Span(start, self._position()))

    def _match(self, expected: str) -> bool:
        if self._peek() != expected:
            return False
        self._advance()
        return True

    def _advance(self) -> str:
        char = self.source[self.offset]
        self.offset += 1
        if char == "\n":
            self.line += 1
            self.column = 1
        else:
            self.column += 1
        return char

    def _peek(self) -> str:
        return "\0" if self._at_end() else self.source[self.offset]

    def _peek_next(self) -> str:
        return (
            "\0"
            if self.offset + 1 >= len(self.source)
            else self.source[self.offset + 1]
        )

    def _position(self) -> Position:
        return Position(self.offset, self.line, self.column)

    def _at_end(self) -> bool:
        return self.offset >= len(self.source)


def tokenize(source: str) -> tuple[Token, ...]:
    """Tokenize NeoQL source."""
    return Lexer(source).tokenize()
