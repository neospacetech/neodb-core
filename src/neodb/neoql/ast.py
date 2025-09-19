"""Abstract Syntax Tree (AST) nodes for NeoQL query language.

This module defines the AST structure for representing parsed NeoQL queries.
"""

from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass
from abc import ABC, abstractmethod


@dataclass
class ASTNode(ABC):
    """Base class for all AST nodes."""
    pass


@dataclass
class Property:
    """Represents a property constraint or assignment."""
    key: str
    value: Any
    operator: str = "="  # =, !=, <, >, <=, >=, CONTAINS, etc.


@dataclass
class NodePattern(ASTNode):
    """Represents a node pattern in a query."""
    variable: Optional[str] = None
    labels: List[str] = None
    properties: List[Property] = None
    
    def __post_init__(self):
        if self.labels is None:
            self.labels = []
        if self.properties is None:
            self.properties = []
    
    def __str__(self) -> str:
        var_str = self.variable or ""
        label_str = ":".join(self.labels) if self.labels else ""
        prop_str = ", ".join(f"{p.key} {p.operator} {p.value}" for p in self.properties)
        
        if label_str and prop_str:
            return f"({var_str}:{label_str} {{ {prop_str} }})"
        elif label_str:
            return f"({var_str}:{label_str})"
        elif prop_str:
            return f"({var_str} {{ {prop_str} }})"
        else:
            return f"({var_str})"


@dataclass
class EdgePattern(ASTNode):
    """Represents an edge pattern in a query."""
    variable: Optional[str] = None
    relationship_type: Optional[str] = None
    properties: List[Property] = None
    direction: str = "outgoing"  # "outgoing", "incoming", "undirected"
    
    def __post_init__(self):
        if self.properties is None:
            self.properties = []
    
    def __str__(self) -> str:
        var_str = self.variable or ""
        type_str = f":{self.relationship_type}" if self.relationship_type else ""
        prop_str = ", ".join(f"{p.key} {p.operator} {p.value}" for p in self.properties)
        
        if prop_str:
            pattern = f"[{var_str}{type_str} {{ {prop_str} }}]"
        else:
            pattern = f"[{var_str}{type_str}]"
        
        if self.direction == "outgoing":
            return f"-{pattern}->"
        elif self.direction == "incoming":
            return f"<-{pattern}-"
        else:
            return f"-{pattern}-"


@dataclass
class PathPattern(ASTNode):
    """Represents a path pattern combining nodes and edges."""
    elements: List[Union[NodePattern, EdgePattern]]
    
    def __str__(self) -> str:
        return "".join(str(elem) for elem in self.elements)


@dataclass
class WhereClause(ASTNode):
    """Represents a WHERE clause with conditions."""
    conditions: List[Property]
    
    def __str__(self) -> str:
        return " AND ".join(f"{c.key} {c.operator} {c.value}" for c in self.conditions)


@dataclass
class ReturnClause(ASTNode):
    """Represents a RETURN clause."""
    items: List[str]  # Variable names or expressions to return
    distinct: bool = False
    limit: Optional[int] = None
    
    def __str__(self) -> str:
        distinct_str = "DISTINCT " if self.distinct else ""
        items_str = ", ".join(self.items)
        limit_str = f" LIMIT {self.limit}" if self.limit else ""
        return f"RETURN {distinct_str}{items_str}{limit_str}"


@dataclass
class MatchClause(ASTNode):
    """Represents a MATCH clause."""
    patterns: List[PathPattern]
    optional: bool = False
    
    def __str__(self) -> str:
        optional_str = "OPTIONAL " if self.optional else ""
        patterns_str = ", ".join(str(p) for p in self.patterns)
        return f"{optional_str}MATCH {patterns_str}"


@dataclass
class CreateClause(ASTNode):
    """Represents a CREATE clause."""
    patterns: List[PathPattern]
    
    def __str__(self) -> str:
        patterns_str = ", ".join(str(p) for p in self.patterns)
        return f"CREATE {patterns_str}"


@dataclass
class SetClause(ASTNode):
    """Represents a SET clause for updating properties."""
    assignments: List[Property]
    
    def __str__(self) -> str:
        assignments_str = ", ".join(f"{a.key} = {a.value}" for a in self.assignments)
        return f"SET {assignments_str}"


@dataclass
class DeleteClause(ASTNode):
    """Represents a DELETE clause."""
    variables: List[str]
    detach: bool = False  # DETACH DELETE removes nodes and their edges
    
    def __str__(self) -> str:
        detach_str = "DETACH " if self.detach else ""
        vars_str = ", ".join(self.variables)
        return f"{detach_str}DELETE {vars_str}"


@dataclass
class Query(ASTNode):
    """Represents a complete NeoQL query."""
    clauses: List[ASTNode]
    
    def __str__(self) -> str:
        return "\n".join(str(clause) for clause in self.clauses)
    
    def get_clauses_by_type(self, clause_type: type) -> List[ASTNode]:
        """Get all clauses of a specific type."""
        return [clause for clause in self.clauses if isinstance(clause, clause_type)]