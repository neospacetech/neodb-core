"""NeoQL frontend diagnostics."""

from .ast import Span


class NeoQLSyntaxError(ValueError):
    """A syntax error with a precise source location."""

    def __init__(self, message: str, span: Span, source: str):
        self.message = message
        self.span = span
        self.source = source
        super().__init__(message)

    @property
    def line(self) -> int:
        return self.span.start.line

    @property
    def column(self) -> int:
        return self.span.start.column

    def __str__(self) -> str:
        lines = self.source.splitlines()
        source_line = lines[self.line - 1] if self.line <= len(lines) else ""
        pointer = " " * (self.column - 1) + "^"
        return (
            f"{self.message} at line {self.line}, column {self.column}\n"
            f"{source_line}\n{pointer}"
        )
