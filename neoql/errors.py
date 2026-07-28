"""Public, machine-readable NeoQL diagnostics."""

from collections.abc import Mapping
from typing import Any, TypeVar

from .ast import Span

DiagnosticT = TypeVar("DiagnosticT", bound="DiagnosticError")


def span_to_dict(span: Span) -> dict[str, Any]:
    """Serialize a source span using one-based line and column positions."""
    return {
        "start": {
            "offset": span.start.offset,
            "line": span.start.line,
            "column": span.start.column,
        },
        "end": {
            "offset": span.end.offset,
            "line": span.end.line,
            "column": span.end.column,
        },
    }


class DiagnosticError(ValueError):
    """Base class for all stable NeoQL and NeoDB diagnostics."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        category: str,
        phase: str,
        span: Span | None = None,
        source: str | None = None,
        details: Mapping[str, Any] | None = None,
        retryable: bool = False,
    ):
        self.code = code
        self.message = message
        self.category = category
        self.phase = phase
        self.span = span
        self.source = source
        self.details = dict(details or {})
        self.retryable = retryable
        super().__init__(message)

    def with_source(
        self: DiagnosticT,
        span: Span,
        source: str | None = None,
    ) -> DiagnosticT:
        """Attach compile-time source context while preserving the error type."""
        self.span = span
        if source is not None:
            self.source = source
        return self

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "error": self.category,
            "code": self.code,
            "message": self.message,
            "phase": self.phase,
            "retryable": self.retryable,
            "details": self.details,
        }
        if self.span is not None:
            payload["location"] = span_to_dict(self.span)
        return payload

    def __str__(self) -> str:
        if self.span is None:
            return self.message
        line = self.span.start.line
        column = self.span.start.column
        diagnostic = f"{self.message} at line {line}, column {column}"
        if not self.source:
            return diagnostic
        lines = self.source.splitlines()
        source_line = lines[line - 1] if line <= len(lines) else ""
        pointer = " " * (column - 1) + "^"
        return f"{diagnostic}\n{source_line}\n{pointer}"


class NeoQLSyntaxError(DiagnosticError):
    """A syntax error with a precise source location."""

    def __init__(self, message: str, span: Span, source: str):
        super().__init__(
            "syntax_error",
            message,
            category="syntax",
            phase="parse",
            span=span,
            source=source,
        )

    @property
    def line(self) -> int:
        assert self.span is not None
        return self.span.start.line

    @property
    def column(self) -> int:
        assert self.span is not None
        return self.span.start.column


class EngineError(DiagnosticError):
    """A planner or runtime engine failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        phase: str = "runtime",
        details: Mapping[str, Any] | None = None,
        retryable: bool = False,
    ):
        super().__init__(
            code,
            message,
            category="engine",
            phase=phase,
            details=details,
            retryable=retryable,
        )


class DatasetNotFoundError(EngineError):
    def __init__(self, dataset: str):
        super().__init__(
            "unknown_dataset",
            f"Dataset '{dataset}' not found",
            phase="plan",
            details={"dataset": dataset},
        )


class DatasetAlreadyExistsError(EngineError):
    def __init__(self, dataset: str):
        super().__init__(
            "dataset_exists",
            f"Dataset '{dataset}' already exists",
            details={"dataset": dataset},
        )


class UnknownFieldError(EngineError):
    def __init__(self, dataset: str, field: str):
        super().__init__(
            "unknown_field",
            f"Unknown field '{field}' in dataset '{dataset}'",
            phase="plan",
            details={"dataset": dataset, "field": field},
        )


class UnsupportedDatasetError(EngineError):
    def __init__(self, dataset_type: str):
        super().__init__(
            "unsupported_dataset_type",
            f"Unsupported dataset type '{dataset_type}'",
            phase="compile",
            details={"dataset_type": dataset_type},
        )


class InvalidTraversalError(EngineError):
    def __init__(self, message: str, **details: Any):
        super().__init__(
            "invalid_traversal",
            message,
            phase="plan",
            details=details,
        )


class MissingReferenceError(EngineError):
    def __init__(self, dataset: str, value: Any):
        super().__init__(
            "missing_reference",
            f"Referenced record in dataset '{dataset}' was not found",
            details={"dataset": dataset, "value": value},
        )


class QueryTimeoutError(EngineError):
    def __init__(self, timeout_ms: int):
        super().__init__(
            "timeout",
            f"Query exceeded its {timeout_ms}ms deadline",
            details={"timeout_ms": timeout_ms},
            retryable=True,
        )


class DeadlockError(EngineError):
    def __init__(self, transaction: str | None = None):
        details = {"transaction": transaction} if transaction else {}
        super().__init__(
            "deadlock",
            "Transaction was aborted because of a deadlock",
            details=details,
            retryable=True,
        )


class PermissionDeniedError(EngineError):
    def __init__(self, operation: str, resource: str | None = None):
        details = {"operation": operation}
        if resource is not None:
            details["resource"] = resource
        super().__init__(
            "permission_denied",
            f"Permission denied for operation '{operation}'",
            details=details,
        )
