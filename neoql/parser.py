"""Recursive-descent NeoQL parser and legacy query adapter."""

from typing import Any, NoReturn

from .ast import (
    AddStatement,
    Comparison,
    Constraint,
    CreateDatasetStatement,
    DeleteStatement,
    FieldDefinition,
    ListLiteral,
    Literal,
    Logical,
    MethodCall,
    Negation,
    ObjectLiteral,
    Predicate,
    Projection,
    ProjectionField,
    RecordField,
    RecordLiteral,
    SelectionStatement,
    Span,
    Statement,
    TypeRef,
    UpdateStatement,
    Value,
)
from .errors import NeoQLSyntaxError
from .lexer import Token, TokenKind, tokenize


class Parser:
    """Parse a single NeoQL statement."""

    def __init__(self, source: str):
        self.source = source
        self.tokens = tokenize(source)
        self.current = 0

    def parse(self) -> Statement:
        statement: Statement
        if self._keyword("create"):
            statement = self._create_dataset()
        elif self._keyword("add"):
            statement = self._add()
        else:
            statement = self._selection()
        self._consume(TokenKind.EOF, "Expected end of statement")
        return statement

    def _create_dataset(self) -> CreateDatasetStatement:
        start = self._previous()
        self._consume_keyword("dataset")
        name = self._consume(TokenKind.IDENTIFIER, "Expected dataset name")
        self._consume(TokenKind.LEFT_PAREN, "Expected '(' after dataset name")
        storage = self._consume(TokenKind.IDENTIFIER, "Expected storage type")
        fields = []
        if self._match(TokenKind.LEFT_BRACE):
            if not self._check(TokenKind.RIGHT_BRACE):
                fields.append(self._field_definition())
                while self._match(TokenKind.COMMA):
                    fields.append(self._field_definition())
            self._consume(TokenKind.RIGHT_BRACE, "Expected '}' after dataset fields")
        end = self._consume(
            TokenKind.RIGHT_PAREN, "Expected ')' after dataset definition"
        )
        return CreateDatasetStatement(
            self._span(start, end),
            name.lexeme,
            storage.lexeme,
            tuple(fields),
        )

    def _field_definition(self) -> FieldDefinition:
        start = self._consume(TokenKind.IDENTIFIER, "Expected field name")
        self._consume(TokenKind.LEFT_PAREN, "Expected '(' after field name")
        type_ref = self._type_ref()
        constraints = []
        while self._match(TokenKind.COMMA):
            constraints.append(self._constraint())
        end = self._consume(
            TokenKind.RIGHT_PAREN, "Expected ')' after field definition"
        )
        return FieldDefinition(
            self._span(start, end),
            start.lexeme,
            type_ref,
            tuple(constraints),
        )

    def _type_ref(self) -> TypeRef:
        name = self._consume(TokenKind.IDENTIFIER, "Expected type name")
        arguments: list[TypeRef | Literal] = []
        end = name
        if self._match(TokenKind.LEFT_PAREN):
            if not self._check(TokenKind.RIGHT_PAREN):
                arguments.append(self._type_argument())
                while self._match(TokenKind.COMMA):
                    arguments.append(self._type_argument())
            end = self._consume(TokenKind.RIGHT_PAREN, "Expected ')' after type")
        return TypeRef(self._span(name, end), name.lexeme, tuple(arguments))

    def _type_argument(self) -> TypeRef | Literal:
        if self._check(TokenKind.IDENTIFIER):
            lowered = self._peek().lexeme.lower()
            if lowered not in {"true", "false", "null", "none"}:
                return self._type_ref()
        value = self._value()
        if not isinstance(value, Literal):
            self._error(self._previous(), "Type arguments must be scalar")
        return value

    def _constraint(self) -> Constraint:
        name = self._consume(TokenKind.IDENTIFIER, "Expected constraint name")
        arguments = []
        end = name
        if self._match(TokenKind.LEFT_PAREN):
            if not self._check(TokenKind.RIGHT_PAREN):
                arguments.append(self._value())
                while self._match(TokenKind.COMMA):
                    arguments.append(self._value())
            end = self._consume(TokenKind.RIGHT_PAREN, "Expected ')' after constraint")
        return Constraint(self._span(name, end), name.lexeme, tuple(arguments))

    def _add(self) -> AddStatement:
        start = self._previous()
        records = [self._record()]
        while self._match(TokenKind.COMMA):
            records.append(self._record())
        self._consume_keyword("into")
        dataset = self._consume(TokenKind.IDENTIFIER, "Expected destination dataset")
        return AddStatement(self._span(start, dataset), tuple(records), dataset.lexeme)

    def _record(self) -> RecordLiteral:
        start = self._consume(TokenKind.LEFT_BRACE, "Expected record literal")
        fields = []
        if not self._check(TokenKind.RIGHT_BRACE):
            fields.append(self._record_field())
            while self._match(TokenKind.COMMA):
                fields.append(self._record_field())
        end = self._consume(TokenKind.RIGHT_BRACE, "Expected '}' after record")
        return RecordLiteral(self._span(start, end), tuple(fields))

    def _record_field(self) -> RecordField:
        name = self._consume(TokenKind.IDENTIFIER, "Expected record field name")
        self._consume(TokenKind.EQUAL, "Expected '=' after record field name")
        value = self._value()
        return RecordField(Span(name.span.start, value.span.end), name.lexeme, value)

    def _selection(
        self,
    ) -> SelectionStatement | UpdateStatement | DeleteStatement:
        dataset = self._consume(TokenKind.IDENTIFIER, "Expected dataset name")
        self._consume(TokenKind.LEFT_PAREN, "Expected '(' after dataset name")
        predicate = None
        if self._match(TokenKind.LEFT_BRACE):
            if not self._check(TokenKind.RIGHT_BRACE):
                predicate = self._predicate()
            self._consume(TokenKind.RIGHT_BRACE, "Expected '}' after predicate")
        end = self._consume(
            TokenKind.RIGHT_PAREN, "Expected ')' after dataset invocation"
        )
        operations: list[Projection | MethodCall] = []
        while self._match(TokenKind.DOT):
            if self._check(TokenKind.IDENTIFIER) and self._peek().lexeme.lower() in {
                "update",
                "delete",
            }:
                if operations:
                    self._error(
                        self._peek(),
                        "Mutations must directly follow a dataset invocation",
                    )
                return self._mutation(dataset, predicate)
            operation: Projection | MethodCall
            if self._check(TokenKind.LEFT_PAREN):
                operation = self._projection()
            else:
                operation = self._method_call()
            operations.append(operation)
            end = self._previous()
        return SelectionStatement(
            Span(dataset.span.start, end.span.end),
            dataset.lexeme,
            predicate,
            tuple(operations),
        )

    def _mutation(
        self,
        dataset: Token,
        predicate: Predicate | None,
    ) -> UpdateStatement | DeleteStatement:
        method = self._advance()
        self._consume(TokenKind.LEFT_PAREN, f"Expected '(' after {method.lexeme}")
        if method.lexeme.lower() == "update":
            values = self._record()
            if not values.fields:
                self._error(method, "update() requires at least one field")
            end = self._consume(
                TokenKind.RIGHT_PAREN,
                "Expected ')' after update values",
            )
            return UpdateStatement(
                Span(dataset.span.start, end.span.end),
                dataset.lexeme,
                predicate,
                values,
            )
        end = self._consume(
            TokenKind.RIGHT_PAREN,
            "delete() does not accept arguments",
        )
        return DeleteStatement(
            Span(dataset.span.start, end.span.end),
            dataset.lexeme,
            predicate,
        )

    def _projection(self) -> Projection:
        start = self._consume(TokenKind.LEFT_PAREN, "Expected '(' for projection")
        fields = []
        if not self._check(TokenKind.RIGHT_PAREN):
            fields.append(self._projection_field())
            while self._match(TokenKind.COMMA):
                fields.append(self._projection_field())
        end = self._consume(TokenKind.RIGHT_PAREN, "Expected ')' after projection")
        return Projection(self._span(start, end), tuple(fields))

    def _projection_field(self) -> ProjectionField:
        name = self._consume(TokenKind.IDENTIFIER, "Expected projected field")
        children = []
        end = name
        if self._match(TokenKind.LEFT_PAREN):
            if not self._check(TokenKind.RIGHT_PAREN):
                children.append(self._projection_field())
                while self._match(TokenKind.COMMA):
                    children.append(self._projection_field())
            end = self._consume(
                TokenKind.RIGHT_PAREN, "Expected ')' after nested projection"
            )
        return ProjectionField(self._span(name, end), name.lexeme, tuple(children))

    def _method_call(self) -> MethodCall:
        name = self._consume(TokenKind.IDENTIFIER, "Expected selection method")
        self._consume(TokenKind.LEFT_PAREN, "Expected '(' after method name")
        arguments: list[Value | str] = []
        if not self._check(TokenKind.RIGHT_PAREN):
            arguments.append(self._method_argument())
            if name.lexeme == "order" and self._check(TokenKind.IDENTIFIER):
                arguments.append(self._advance().lexeme)
            while self._match(TokenKind.COMMA):
                arguments.append(self._method_argument())
        end = self._consume(TokenKind.RIGHT_PAREN, "Expected ')' after method")
        return MethodCall(self._span(name, end), name.lexeme, tuple(arguments))

    def _method_argument(self) -> Value | str:
        if self._check(TokenKind.IDENTIFIER):
            token = self._advance()
            return token.lexeme
        return self._value()

    def _predicate(self) -> Predicate:
        return self._or()

    def _or(self) -> Predicate:
        left = self._and()
        operands = [left]
        while self._match(TokenKind.OR):
            operands.append(self._and())
        if len(operands) == 1:
            return left
        return Logical(
            Span(operands[0].span.start, operands[-1].span.end),
            "or",
            tuple(operands),
        )

    def _and(self) -> Predicate:
        left = self._unary()
        operands = [left]
        while self._match(TokenKind.AND, TokenKind.COMMA):
            operands.append(self._unary())
        if len(operands) == 1:
            return left
        return Logical(
            Span(operands[0].span.start, operands[-1].span.end),
            "and",
            tuple(operands),
        )

    def _unary(self) -> Predicate:
        if self._match(TokenKind.NOT):
            start = self._previous()
            operand = self._unary()
            return Negation(Span(start.span.start, operand.span.end), operand)
        if self._match(TokenKind.LEFT_PAREN):
            predicate = self._predicate()
            self._consume(
                TokenKind.RIGHT_PAREN, "Expected ')' after predicate expression"
            )
            return predicate
        return self._comparison()

    def _comparison(self) -> Comparison:
        field = self._consume(TokenKind.IDENTIFIER, "Expected predicate field")
        operator_tokens = {
            TokenKind.EQUAL: "=",
            TokenKind.NOT_EQUAL: "!=",
            TokenKind.GREATER: ">",
            TokenKind.GREATER_EQUAL: ">=",
            TokenKind.LESS: "<",
            TokenKind.LESS_EQUAL: "<=",
        }
        operator = None
        for kind, spelling in operator_tokens.items():
            if self._match(kind):
                operator = spelling
                break
        if operator is None and self._check(TokenKind.IDENTIFIER):
            candidate = self._peek().lexeme
            if candidate in {
                "in",
                "contains",
                "startsWith",
                "endsWith",
                "matches",
            }:
                operator = self._advance().lexeme
        if operator is None:
            self._error(self._peek(), "Expected predicate operator")
        value = self._value()
        return Comparison(
            Span(field.span.start, value.span.end),
            field.lexeme,
            operator,
            value,
        )

    def _value(self) -> Value:
        if self._match(TokenKind.NUMBER, TokenKind.STRING):
            token = self._previous()
            return Literal(token.span, token.value)
        if self._match(TokenKind.IDENTIFIER):
            token = self._previous()
            keyword_values = {
                "true": True,
                "false": False,
                "null": None,
                "none": None,
            }
            return Literal(
                token.span,
                keyword_values.get(token.lexeme.lower(), token.lexeme),
            )
        if self._match(TokenKind.LEFT_BRACKET):
            start = self._previous()
            values = []
            if not self._check(TokenKind.RIGHT_BRACKET):
                values.append(self._value())
                while self._match(TokenKind.COMMA):
                    values.append(self._value())
            end = self._consume(TokenKind.RIGHT_BRACKET, "Expected ']' after list")
            return ListLiteral(self._span(start, end), tuple(values))
        if self._check(TokenKind.LEFT_BRACE):
            record = self._record()
            return ObjectLiteral(record.span, record.fields)
        self._error(self._peek(), "Expected literal value")

    def _keyword(self, keyword: str) -> bool:
        if self._check(TokenKind.IDENTIFIER) and self._peek().lexeme.lower() == keyword:
            self._advance()
            return True
        return False

    def _consume_keyword(self, keyword: str) -> Token:
        if self._keyword(keyword):
            return self._previous()
        self._error(self._peek(), f"Expected '{keyword}'")

    def _match(self, *kinds: TokenKind) -> bool:
        if any(self._check(kind) for kind in kinds):
            self._advance()
            return True
        return False

    def _consume(self, kind: TokenKind, message: str) -> Token:
        if self._check(kind):
            return self._advance()
        self._error(self._peek(), message)

    def _check(self, kind: TokenKind) -> bool:
        return self._peek().kind == kind

    def _advance(self) -> Token:
        token = self._peek()
        if token.kind != TokenKind.EOF:
            self.current += 1
        return token

    def _peek(self) -> Token:
        return self.tokens[self.current]

    def _previous(self) -> Token:
        return self.tokens[self.current - 1]

    def _span(self, start: Token, end: Token) -> Span:
        return Span(start.span.start, end.span.end)

    def _error(self, token: Token, message: str) -> NoReturn:
        raise NeoQLSyntaxError(message, token.span, self.source)


def parse_statement(source: str) -> Statement:
    """Parse one complete NeoQL statement."""
    return Parser(source).parse()


def _value_to_python(value: Value) -> Any:
    if isinstance(value, ListLiteral):
        return [_value_to_python(item) for item in value.values]
    if isinstance(value, ObjectLiteral):
        return {field.name: _value_to_python(field.value) for field in value.fields}
    return value.value


def _predicate_to_query(predicate: Predicate | None) -> dict[str, Any] | None:
    if predicate is None:
        return None
    if isinstance(predicate, Comparison):
        return {
            "field": predicate.field,
            "op": predicate.operator,
            "value": _value_to_python(predicate.value),
        }
    if isinstance(predicate, Negation):
        return {"not": _predicate_to_query(predicate.operand)}
    return {
        predicate.operator: [
            _predicate_to_query(operand) for operand in predicate.operands
        ]
    }


def _record_to_dict(record: RecordLiteral) -> dict[str, Any]:
    return {field.name: _value_to_python(field.value) for field in record.fields}


def statement_to_query(statement: Statement) -> dict[str, Any]:
    """Adapt an AST statement to the current engine query contract."""
    if isinstance(statement, CreateDatasetStatement):
        from .schema import DatasetSchema, SchemaDefinitionError
        from .types import NeoQLTypeError, resolve_type

        schema = {}
        for field in statement.fields:
            if field.name in schema:
                raise SchemaDefinitionError(
                    f"Duplicate field '{field.name}'", field=field.name
                ).with_source(field.span)
            try:
                resolved_type = resolve_type(field.type_ref)
            except NeoQLTypeError as error:
                raise error.with_source(field.type_ref.span) from error
            entry: dict[str, Any] = {"type": resolved_type.display()}
            if field.constraints:
                constraints: list[str | dict[str, Any]] = []
                for constraint in field.constraints:
                    if constraint.arguments:
                        constraints.append(
                            {
                                "name": constraint.name,
                                "arguments": [
                                    _value_to_python(argument)
                                    for argument in constraint.arguments
                                ],
                            }
                        )
                    else:
                        constraints.append(constraint.name)
                entry["constraints"] = constraints
            schema[field.name] = entry
        try:
            DatasetSchema.from_mapping(statement.name, schema)
        except SchemaDefinitionError as error:
            matching = next(
                (field for field in statement.fields if field.name == error.field),
                None,
            )
            raise error.with_source(
                matching.span if matching is not None else statement.span
            ) from error
        query: dict[str, Any] = {
            "action": "create_dataset",
            "name": statement.name,
            "type": statement.storage,
        }
        if schema:
            query["schema"] = schema
        return query
    if isinstance(statement, AddStatement):
        return {
            "action": "insert",
            "dataset": statement.dataset,
            "objects": [_record_to_dict(record) for record in statement.records],
        }
    if isinstance(statement, UpdateStatement):
        return {
            "action": "update",
            "dataset": statement.dataset,
            "filter": _predicate_to_query(statement.predicate),
            "values": _record_to_dict(statement.values),
        }
    if isinstance(statement, DeleteStatement):
        return {
            "action": "delete",
            "dataset": statement.dataset,
            "filter": _predicate_to_query(statement.predicate),
        }
    query = {
        "action": "select",
        "dataset": statement.dataset,
        "filter": _predicate_to_query(statement.predicate),
    }
    grouping = False
    aggregated = False
    for operation in statement.operations:
        if aggregated:
            raise NeoQLSyntaxError(
                "Aggregation must be the final Selection operation",
                operation.span,
                "",
            )
        if isinstance(operation, Projection):
            if grouping:
                raise NeoQLSyntaxError(
                    "Only an aggregation may follow group()",
                    operation.span,
                    "",
                )
            query["select"] = [field.name for field in operation.fields]
            continue
        aggregate_methods = {
            "count",
            "sum",
            "avg",
            "min",
            "max",
            "median",
            "std",
        }
        if grouping and operation.name not in aggregate_methods:
            raise NeoQLSyntaxError(
                "Only an aggregation may follow group()",
                operation.span,
                "",
            )
        if operation.name == "order":
            if not operation.arguments or not isinstance(operation.arguments[0], str):
                raise NeoQLSyntaxError(
                    "order() expects a field name",
                    operation.span,
                    "",
                )
            direction = "asc"
            if len(operation.arguments) > 1:
                direction = str(operation.arguments[1]).lower()
            if direction not in {"asc", "desc"}:
                raise NeoQLSyntaxError(
                    "order direction must be 'asc' or 'desc'",
                    operation.span,
                    "",
                )
            query.setdefault("order_by", []).append(
                {"field": operation.arguments[0], "direction": direction}
            )
        elif operation.name in {"limit", "offset"}:
            if (
                len(operation.arguments) != 1
                or not isinstance(operation.arguments[0], Literal)
                or not isinstance(operation.arguments[0].value, int)
            ):
                raise NeoQLSyntaxError(
                    f"{operation.name}() expects one integer",
                    operation.span,
                    "",
                )
            query[operation.name] = operation.arguments[0].value
        elif operation.name == "group":
            if (
                grouping
                or len(operation.arguments) != 1
                or not isinstance(operation.arguments[0], str)
            ):
                raise NeoQLSyntaxError(
                    "group() expects one field name",
                    operation.span,
                    "",
                )
            query["group_by"] = operation.arguments[0]
            grouping = True
        elif operation.name in aggregate_methods:
            expects_field = operation.name != "count"
            valid_arguments = (
                len(operation.arguments) == 1
                and isinstance(operation.arguments[0], str)
                if expects_field
                else not operation.arguments
            )
            if not valid_arguments:
                expectation = "one field name" if expects_field else "no arguments"
                raise NeoQLSyntaxError(
                    f"{operation.name}() expects {expectation}",
                    operation.span,
                    "",
                )
            aggregate: dict[str, Any] = {"operation": operation.name}
            if expects_field:
                aggregate["field"] = operation.arguments[0]
            query["aggregate"] = aggregate
            aggregated = True
        else:
            raise NeoQLSyntaxError(
                f"Unsupported selection method '{operation.name}'",
                operation.span,
                "",
            )
    return query
