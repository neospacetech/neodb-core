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


class ResolutionError(DiagnosticError):
    """A source-located language name or binding error."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ):
        super().__init__(
            code,
            message,
            category="resolution",
            phase="resolve",
            details=details,
        )


class UnknownNameError(ResolutionError):
    def __init__(self, name: str):
        super().__init__(
            "unknown_name",
            f"Unknown name '{name}'",
            details={"name": name},
        )


class ImmutableBindingError(ResolutionError):
    def __init__(self, name: str):
        super().__init__(
            "immutable_binding",
            f"Cannot reassign immutable binding '{name}'",
            details={"name": name},
        )


class UnknownFunctionError(ResolutionError):
    def __init__(self, name: str):
        super().__init__(
            "unknown_function",
            f"Unknown function '{name}'",
            details={"function": name},
        )


class FunctionArityError(ResolutionError):
    def __init__(self, name: str, expected: int, actual: int):
        super().__init__(
            "function_arity",
            f"Function '{name}' expects {expected} arguments, received {actual}",
            details={"function": name, "expected": expected, "actual": actual},
        )


class RecursionNotAllowedError(ResolutionError):
    def __init__(self, name: str):
        super().__init__(
            "recursion_not_allowed",
            f"Recursive call to '{name}' is not allowed",
            details={"function": name},
        )


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


class AmbiguousReferenceError(EngineError):
    def __init__(self, dataset: str, value: Any):
        super().__init__(
            "ambiguous_reference",
            f"Reference identity is ambiguous in dataset '{dataset}'",
            details={"dataset": dataset, "value": value},
        )


class ReferenceCycleError(EngineError):
    def __init__(self, path: list[str]):
        super().__init__(
            "reference_cycle",
            "Cyclic inline reference detected",
            details={"path": path},
        )


class ReferenceConflictError(EngineError):
    def __init__(self, dataset: str, fields: list[str]):
        super().__init__(
            "reference_conflict",
            f"Inline reference conflicts with dataset '{dataset}'",
            details={"dataset": dataset, "fields": fields},
        )


class ReferenceInUseError(EngineError):
    def __init__(self, dataset: str, source_dataset: str):
        super().__init__(
            "reference_in_use",
            f"Cannot mutate referenced identity in dataset '{dataset}'",
            details={
                "dataset": dataset,
                "source_dataset": source_dataset,
            },
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
