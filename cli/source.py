"""Multiline NeoQL source buffering and script statement splitting."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ScriptStatement:
    source: str
    start_line: int


class StatementBuffer:
    """Collect physical input lines until complete NeoQL statements exist."""

    def __init__(self):
        self._source = ""

    @property
    def pending(self) -> bool:
        return bool(_meaningful(self._source))

    def feed(self, line: str) -> list[str]:
        self._source += f"{line}\n"
        statements, self._source, _line = _split_complete(self._source, eof=False)
        return [statement.source for statement in statements]

    def finish(self) -> list[str]:
        statements, remainder, start_line = _split_complete(self._source, eof=True)
        if _meaningful(remainder):
            statements.append(ScriptStatement(remainder.strip(), start_line))
        self._source = ""
        return [statement.source for statement in statements]


def split_script(source: str) -> list[ScriptStatement]:
    """Split a NeoQL file on complete top-level lines or semicolons."""
    statements, remainder, start_line = _split_complete(source, eof=True)
    if _meaningful(remainder):
        statements.append(ScriptStatement(remainder.strip(), start_line))
    return statements


def _split_complete(
    source: str,
    *,
    eof: bool,
) -> tuple[list[ScriptStatement], str, int]:
    statements = []
    stack: list[str] = []
    quote: str | None = None
    escaped = False
    comment = False
    start = 0
    start_line = 1
    line = 1
    last_significant = ""
    pairs = {")": "(", "}": "{", "]": "["}

    for index, char in enumerate(source):
        if comment:
            if char == "\n":
                comment = False
            else:
                continue
        elif quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
                last_significant = char
        elif char in {"'", '"'}:
            quote = char
            last_significant = char
        elif char == "#":
            comment = True
        elif char == "/" and index + 1 < len(source) and source[index + 1] == "/":
            comment = True
        elif char in "({[":
            stack.append(char)
            last_significant = char
        elif char in ")}]":
            if stack and stack[-1] == pairs[char]:
                stack.pop()
            else:
                stack.clear()
            last_significant = char
        elif not char.isspace() and char != ";":
            last_significant = char

        boundary = (
            quote is None
            and not comment
            and not stack
            and (
                char == ";"
                or (
                    char == "\n"
                    and last_significant
                    not in {"", ".", ",", "=", "&", "|", "+", "-", "*", "^"}
                    and not _requires_continuation(source[start:index])
                )
            )
        )
        if boundary:
            candidate = source[start:index]
            if _meaningful(candidate):
                statements.append(ScriptStatement(candidate.strip(), start_line))
            start = index + 1
            start_line = line + (1 if char == "\n" else 0)
            last_significant = ""
        if char == "\n":
            line += 1

    remainder = source[start:]
    if eof and quote is None and not stack and _meaningful(remainder):
        statements.append(ScriptStatement(remainder.strip(), start_line))
        remainder = ""
        start_line = line
    return statements, remainder, start_line


def _requires_continuation(candidate: str) -> bool:
    meaningful = _meaningful(candidate).lower()
    if meaningful.startswith("add link") and "between" not in meaningful.split():
        return True
    return meaningful.endswith("between")


def _meaningful(source: str) -> str:
    meaningful = []
    quote: str | None = None
    escaped = False
    for line in source.splitlines():
        result = []
        index = 0
        while index < len(line):
            char = line[index]
            if quote is not None:
                result.append(char)
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = None
            elif char in {"'", '"'}:
                quote = char
                result.append(char)
            elif char == "#" or (char == "/" and line[index : index + 2] == "//"):
                break
            else:
                result.append(char)
            index += 1
        meaningful.append("".join(result))
    return "\n".join(meaningful).strip()
