"""NeoQL language frontend."""

from .ast import (
    AddStatement,
    CreateDatasetStatement,
    SelectionStatement,
    Statement,
)
from .errors import (
    DatasetAlreadyExistsError,
    DatasetNotFoundError,
    DeadlockError,
    DiagnosticError,
    EngineError,
    InvalidTraversalError,
    MissingReferenceError,
    NeoQLSyntaxError,
    PermissionDeniedError,
    QueryTimeoutError,
    UnknownFieldError,
    UnsupportedDatasetError,
    span_to_dict,
)
from .lexer import Lexer, Token, TokenKind, tokenize
from .parser import parse_statement, statement_to_query
from .predicates import (
    PredicateEvaluationError,
    evaluate_operator,
    evaluate_predicate,
    validate_predicate,
)
from .schema import (
    ConstraintViolation,
    DatasetSchema,
    FieldSchema,
    IndexMetadata,
    SchemaDefinitionError,
)
from .types import (
    NeoQLTypeError,
    TypeDescriptor,
    TypeKind,
    cast_value,
    infer_type,
    parse_type,
    resolve_type,
)

__all__ = [
    "AddStatement",
    "CreateDatasetStatement",
    "ConstraintViolation",
    "DatasetAlreadyExistsError",
    "DatasetSchema",
    "DatasetNotFoundError",
    "DeadlockError",
    "DiagnosticError",
    "EngineError",
    "FieldSchema",
    "IndexMetadata",
    "InvalidTraversalError",
    "Lexer",
    "NeoQLSyntaxError",
    "NeoQLTypeError",
    "MissingReferenceError",
    "PermissionDeniedError",
    "PredicateEvaluationError",
    "QueryTimeoutError",
    "SelectionStatement",
    "SchemaDefinitionError",
    "Statement",
    "Token",
    "TokenKind",
    "TypeDescriptor",
    "TypeKind",
    "UnknownFieldError",
    "UnsupportedDatasetError",
    "cast_value",
    "evaluate_operator",
    "evaluate_predicate",
    "infer_type",
    "parse_type",
    "parse_statement",
    "statement_to_query",
    "span_to_dict",
    "tokenize",
    "validate_predicate",
    "resolve_type",
]
