"""Typed, source-located abstract syntax tree nodes for NeoQL."""

from dataclasses import dataclass
from typing import Any, TypeAlias


@dataclass(frozen=True, slots=True)
class Position:
    """A zero-based offset and one-based human-readable source position."""

    offset: int
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class Span:
    """Half-open source range."""

    start: Position
    end: Position


@dataclass(frozen=True, slots=True)
class Node:
    span: Span


@dataclass(frozen=True, slots=True)
class Literal(Node):
    value: Any


@dataclass(frozen=True, slots=True)
class ParameterReference(Node):
    name: str


@dataclass(frozen=True, slots=True)
class FunctionCallValue(Node):
    name: str
    arguments: tuple["Value", ...]


@dataclass(frozen=True, slots=True)
class TypeValue(Node):
    type_ref: "TypeRef"


@dataclass(frozen=True, slots=True)
class SelectionValue(Node):
    expression: "Expression"


@dataclass(frozen=True, slots=True)
class ListLiteral(Node):
    values: tuple["Value", ...]


@dataclass(frozen=True, slots=True)
class ObjectLiteral(Node):
    fields: tuple["RecordField", ...]


Value: TypeAlias = (
    Literal
    | ParameterReference
    | FunctionCallValue
    | TypeValue
    | SelectionValue
    | ListLiteral
    | ObjectLiteral
)


@dataclass(frozen=True, slots=True)
class RecordField(Node):
    name: str
    value: Value


@dataclass(frozen=True, slots=True)
class RecordLiteral(Node):
    fields: tuple[RecordField, ...]


@dataclass(frozen=True, slots=True)
class TypeRef(Node):
    name: str
    arguments: tuple["TypeRef | Literal", ...] = ()

    def render(self) -> str:
        if not self.arguments:
            return self.name
        rendered = []
        for argument in self.arguments:
            if isinstance(argument, TypeRef):
                rendered.append(argument.render())
            else:
                rendered.append(str(argument.value))
        return f"{self.name}({', '.join(rendered)})"


@dataclass(frozen=True, slots=True)
class Constraint(Node):
    name: str
    arguments: tuple[Value, ...] = ()


@dataclass(frozen=True, slots=True)
class FieldDefinition(Node):
    name: str
    type_ref: TypeRef
    constraints: tuple[Constraint, ...] = ()


@dataclass(frozen=True, slots=True)
class Comparison(Node):
    field: str
    operator: str
    value: Value


@dataclass(frozen=True, slots=True)
class Logical(Node):
    operator: str
    operands: tuple["Predicate", ...]


@dataclass(frozen=True, slots=True)
class Negation(Node):
    operand: "Predicate"


Predicate: TypeAlias = Comparison | Logical | Negation


@dataclass(frozen=True, slots=True)
class ProjectionField(Node):
    name: str
    children: tuple["ProjectionField", ...] = ()


@dataclass(frozen=True, slots=True)
class Projection(Node):
    fields: tuple[ProjectionField, ...]


@dataclass(frozen=True, slots=True)
class MethodCall(Node):
    name: str
    arguments: tuple[Value | str, ...]


@dataclass(frozen=True, slots=True)
class WhereOperation(Node):
    predicate: Predicate


@dataclass(frozen=True, slots=True)
class RelationshipExpression(Node):
    label: str
    predicate: Predicate | None = None


@dataclass(frozen=True, slots=True)
class TraversalOperation(Node):
    relationship: RelationshipExpression
    depth: int = 1


@dataclass(frozen=True, slots=True)
class DatasetOptions(Node):
    fields: tuple["RecordField", ...]


SelectionOperation: TypeAlias = (
    Projection | MethodCall | WhereOperation | TraversalOperation
)


@dataclass(frozen=True, slots=True)
class CreateDatasetStatement(Node):
    name: str
    storage: str
    fields: tuple[FieldDefinition, ...]


@dataclass(frozen=True, slots=True)
class AddStatement(Node):
    records: tuple[RecordLiteral, ...]
    dataset: str


@dataclass(frozen=True, slots=True)
class AddSelectionStatement(Node):
    source: "Expression"
    dataset: str


@dataclass(frozen=True, slots=True)
class AddLinkStatement(Node):
    properties: RecordLiteral
    source: "SelectionStatement"
    target: "SelectionStatement"


@dataclass(frozen=True, slots=True)
class SelectionStatement(Node):
    dataset: str
    predicate: Predicate | None
    operations: tuple[SelectionOperation, ...] = ()
    options: DatasetOptions | None = None


@dataclass(frozen=True, slots=True)
class UpdateStatement(Node):
    dataset: str
    predicate: Predicate | None
    values: RecordLiteral


@dataclass(frozen=True, slots=True)
class DeleteStatement(Node):
    dataset: str
    predicate: Predicate | None


@dataclass(frozen=True, slots=True)
class VariableAssignmentStatement(Node):
    name: str
    expression: "Expression"


@dataclass(frozen=True, slots=True)
class VariableReferenceStatement(Node):
    name: str


@dataclass(frozen=True, slots=True)
class FunctionDeclarationStatement(Node):
    name: str
    parameters: tuple[str, ...]
    body: "Expression"


@dataclass(frozen=True, slots=True)
class FunctionCallStatement(Node):
    name: str
    arguments: tuple[Value, ...]


@dataclass(frozen=True, slots=True)
class AlgebraExpression(Node):
    left: "Expression"
    operator: str
    right: "Expression"


@dataclass(frozen=True, slots=True)
class SelectionPipelineExpression(Node):
    base: "Expression"
    operations: tuple[SelectionOperation, ...]


Expression: TypeAlias = (
    SelectionStatement
    | VariableReferenceStatement
    | FunctionCallStatement
    | AlgebraExpression
    | SelectionPipelineExpression
)


Statement: TypeAlias = (
    CreateDatasetStatement
    | AddStatement
    | AddSelectionStatement
    | AddLinkStatement
    | SelectionStatement
    | UpdateStatement
    | DeleteStatement
    | VariableAssignmentStatement
    | VariableReferenceStatement
    | FunctionDeclarationStatement
    | FunctionCallStatement
    | AlgebraExpression
    | SelectionPipelineExpression
)
