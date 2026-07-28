"""Session-scoped immutable bindings and user-defined NeoQL functions."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from .ast import (
    AddSelectionStatement,
    AlgebraExpression,
    CreateDatasetStatement,
    FunctionCallStatement,
    FunctionCallValue,
    FunctionDeclarationStatement,
    Literal,
    ObjectLiteral,
    ParameterReference,
    SelectionPipelineExpression,
    SelectionStatement,
    SelectionValue,
    Statement,
    TypeValue,
    Value,
    VariableAssignmentStatement,
    VariableReferenceStatement,
)
from .builtins import (
    VALUE_FUNCTION_NAMES,
    BuiltinContext,
    call_value_function,
    default_builtin_context,
)
from .errors import (
    EngineError,
    FunctionArityError,
    FunctionTypeError,
    ImmutableBindingError,
    RecursionNotAllowedError,
    UnknownFunctionError,
    UnknownNameError,
)
from .parser import parse_statement, statement_to_query
from .references import SelectionRecordsValue
from .selection import Selection
from .types import NeoQLTypeError, resolve_type

if TYPE_CHECKING:
    from engine import NeoDBEngine


@dataclass(frozen=True, slots=True)
class FunctionDefinition:
    """A parsed function declaration retained by one language session."""

    declaration: FunctionDeclarationStatement
    source: str


class NeoQLSession:
    """Execute NeoQL with session-local variables and functions."""

    def __init__(
        self,
        engine: NeoDBEngine | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
        uuid_source: Callable[[], UUID] | None = None,
    ):
        if engine is None:
            from engine import NeoDBEngine

            engine = NeoDBEngine()
        self.engine = engine
        self.variables: dict[str, Any] = {}
        self.functions: dict[str, FunctionDefinition] = {}
        self._calls: list[str] = []
        defaults = default_builtin_context()
        self._builtin_context = BuiltinContext(
            clock or defaults.clock,
            uuid_source or defaults.uuid_source,
        )

    def execute(self, source: str) -> Any:
        """Parse and execute one statement while preserving session bindings."""
        statement = parse_statement(source)
        return self.execute_statement(statement, source=source)

    def execute_statement(
        self,
        statement: Statement,
        *,
        source: str = "",
        parameters: Mapping[str, Any] | None = None,
    ) -> Any:
        bindings = parameters or {}
        if isinstance(statement, VariableAssignmentStatement):
            self._ensure_unbound(statement.name, statement.span, source)
            value = self._evaluate(statement.expression, source, bindings)
            self.variables[statement.name] = value
            return {"status": "bound", "name": statement.name}
        if isinstance(statement, FunctionDeclarationStatement):
            self._ensure_unbound(statement.name, statement.span, source)
            self.functions[statement.name] = FunctionDefinition(statement, source)
            return {"status": "defined", "function": statement.name}
        if isinstance(statement, CreateDatasetStatement):
            self._ensure_unbound(statement.name, statement.span, source)
        return self._evaluate(statement, source, bindings)

    def _evaluate(
        self,
        statement: Statement,
        source: str,
        parameters: Mapping[str, Any],
    ) -> Any:
        if isinstance(statement, AddSelectionStatement):
            source_selection = self._require_selection(
                self._evaluate(statement.source, source, parameters),
                statement.source.span,
                source,
            )
            records = source_selection.consume()
            return self.engine.execute_query(
                {
                    "action": "insert",
                    "dataset": statement.dataset,
                    "objects": records,
                }
            )
        if isinstance(statement, AlgebraExpression):
            left = self._require_selection(
                self._evaluate(statement.left, source, parameters),
                statement.left.span,
                source,
            )
            right = self._require_selection(
                self._evaluate(statement.right, source, parameters),
                statement.right.span,
                source,
            )
            return left._algebra(
                statement.operator,
                right,
                span=statement.span,
                source=source,
            )
        if isinstance(statement, SelectionPipelineExpression):
            base = self._require_selection(
                self._evaluate(statement.base, source, parameters),
                statement.base.span,
                source,
            )
            pipeline = SelectionStatement(
                statement.span,
                "__pipeline__",
                None,
                statement.operations,
            )
            query = self._compile_query(pipeline, parameters, source)
            return self._finish_selection(base.refine(query), query)
        if isinstance(statement, VariableReferenceStatement):
            if statement.name in parameters:
                return parameters[statement.name]
            if statement.name not in self.variables:
                raise UnknownNameError(statement.name).with_source(
                    statement.span, source
                )
            return self.variables[statement.name]
        if isinstance(statement, FunctionCallStatement):
            arguments = [
                self._value(argument, parameters, source)
                for argument in statement.arguments
            ]
            return self._call(statement.name, arguments, statement.span, source)
        if isinstance(statement, SelectionStatement):
            if statement.dataset in self.variables:
                value = self.variables[statement.dataset]
                if not isinstance(value, Selection):
                    raise UnknownNameError(statement.dataset).with_source(
                        statement.span, source
                    )
                query = self._compile_query(statement, parameters, source)
                return self._finish_selection(value.refine(query), query)
            if statement.dataset not in self.engine.datasets:
                if (
                    statement.predicate is None
                    and not statement.operations
                    and (
                        statement.dataset in self.functions
                        or statement.dataset.lower() in VALUE_FUNCTION_NAMES
                    )
                ):
                    return self._call(statement.dataset, [], statement.span, source)
            query = self._compile_query(statement, parameters, source)
            return self.engine.execute_query(query)
        query = self._compile_query(statement, parameters, source)
        return self.engine.execute_query(query)

    def _compile_query(
        self,
        statement: Statement,
        parameters: Mapping[str, Any],
        source: str,
    ) -> dict[str, Any]:
        return statement_to_query(
            statement,
            parameters,
            lambda value: self._resolve_embedded_value(
                value,
                source,
                parameters,
            ),
        )

    @staticmethod
    def _require_selection(value: Any, span: Any, source: str) -> Selection:
        if not isinstance(value, Selection):
            raise EngineError(
                "invalid_selection_operand",
                "Selection expression requires a Selection value",
                phase="plan",
                details={"actual": type(value).__name__},
            ).with_source(span, source)
        return value

    def _resolve_embedded_value(
        self,
        value: SelectionValue | FunctionCallValue,
        source: str,
        parameters: Mapping[str, Any],
    ) -> Any:
        if isinstance(value, SelectionValue):
            return self._resolve_selection_value(value, source, parameters)
        return self._value(value, parameters, source)

    def _resolve_selection_value(
        self,
        value: SelectionValue,
        source: str,
        parameters: Mapping[str, Any],
    ) -> SelectionRecordsValue:
        selection = self._require_selection(
            self._evaluate(value.expression, source, parameters),
            value.span,
            source,
        )
        return SelectionRecordsValue(
            selection.dataset,
            tuple(selection.consume()),
        )

    def _call(
        self,
        name: str,
        arguments: list[Any],
        span: Any,
        source: str,
    ) -> Any:
        definition = self.functions.get(name)
        if definition is None:
            if name.lower() in VALUE_FUNCTION_NAMES:
                try:
                    return call_value_function(
                        name,
                        arguments,
                        self._builtin_context,
                    )
                except (
                    FunctionArityError,
                    FunctionTypeError,
                    NeoQLTypeError,
                ) as error:
                    raise error.with_source(span, source) from None
            raise UnknownFunctionError(name).with_source(span, source)
        declaration = definition.declaration
        if len(arguments) != len(declaration.parameters):
            raise FunctionArityError(
                name, len(declaration.parameters), len(arguments)
            ).with_source(span, source)
        if name in self._calls:
            raise RecursionNotAllowedError(name).with_source(span, source)
        local = dict(zip(declaration.parameters, arguments, strict=True))
        self._calls.append(name)
        try:
            return self._evaluate(declaration.body, definition.source, local)
        finally:
            self._calls.pop()

    def _ensure_unbound(self, name: str, span: Any, source: str) -> None:
        if (
            name in self.variables
            or name in self.functions
            or name in self.engine.datasets
        ):
            raise ImmutableBindingError(name).with_source(span, source)

    def _value(
        self,
        value: Value,
        parameters: Mapping[str, Any],
        source: str,
    ) -> Any:
        if isinstance(value, ParameterReference):
            if value.name not in parameters:
                raise UnknownNameError(value.name).with_source(value.span, source)
            return parameters[value.name]
        if isinstance(value, Literal):
            return value.value
        if isinstance(value, TypeValue):
            try:
                return resolve_type(value.type_ref)
            except NeoQLTypeError as error:
                raise error.with_source(value.span, source) from None
        if isinstance(value, FunctionCallValue):
            arguments = [
                self._value(argument, parameters, source)
                for argument in value.arguments
            ]
            return self._call(value.name, arguments, value.span, source)
        if isinstance(value, ObjectLiteral):
            return {
                field.name: self._value(field.value, parameters, source)
                for field in value.fields
            }
        if isinstance(value, SelectionValue):
            return self._resolve_selection_value(value, source, parameters)
        return [self._value(item, parameters, source) for item in value.values]

    @staticmethod
    def _finish_selection(selection: Selection, query: Mapping[str, Any]) -> Any:
        if query.get("explain"):
            return selection.explain()
        result: Any = selection
        group_field = query.get("group_by")
        if group_field is not None:
            result = result.group(group_field)
        aggregate = query.get("aggregate")
        if aggregate is not None:
            arguments = [aggregate["field"]] if "field" in aggregate else []
            result = getattr(result, aggregate["operation"])(*arguments)
        return result
