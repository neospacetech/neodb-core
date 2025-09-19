"""NeoQL query language parser for NeoDB.

This module provides a simple parser for the NeoQL query language,
which is inspired by Cypher but simplified for the MVP.
"""

import re
from typing import Any, Dict, List, Optional, Tuple, Union
from .ast import (
    Query, MatchClause, CreateClause, ReturnClause, WhereClause,
    SetClause, DeleteClause, NodePattern, EdgePattern, PathPattern, Property
)


class ParseError(Exception):
    """Exception raised when parsing fails."""
    pass


class NeoQLParser:
    """Simple NeoQL query parser.
    
    Supports basic query patterns:
    - MATCH (n:Label {prop: value})-[r:TYPE]->(m)
    - CREATE (n:Label {prop: value})
    - RETURN n, r, m
    - WHERE n.prop = value
    - SET n.prop = value
    - DELETE n
    """
    
    def __init__(self):
        self.tokens = []
        self.position = 0
    
    def parse(self, query: str) -> Query:
        """Parse a NeoQL query string into an AST."""
        self.tokens = self._tokenize(query)
        self.position = 0
        
        clauses = []
        
        while self.position < len(self.tokens):
            token = self._peek()
            if not token:
                break
                
            if token.upper() == "MATCH":
                clauses.append(self._parse_match())
            elif token.upper() == "OPTIONAL":
                # Look ahead for OPTIONAL MATCH
                if self.position + 1 < len(self.tokens) and self.tokens[self.position + 1].upper() == "MATCH":
                    clauses.append(self._parse_optional_match())
                else:
                    raise ParseError(f"Unexpected token after OPTIONAL: {self.tokens[self.position + 1]}")
            elif token.upper() == "CREATE":
                clauses.append(self._parse_create())
            elif token.upper() == "RETURN":
                clauses.append(self._parse_return())
            elif token.upper() == "WHERE":
                clauses.append(self._parse_where())
            elif token.upper() == "SET":
                clauses.append(self._parse_set())
            elif token.upper() == "DELETE":
                clauses.append(self._parse_delete())
            elif token.upper() == "DETACH":
                clauses.append(self._parse_detach_delete())
            else:
                # Skip unexpected tokens that might be part of complex patterns
                self._advance()
        
        return Query(clauses)
    
    def _tokenize(self, query: str) -> List[str]:
        """Tokenize a query string."""
        # Simple regex-based tokenizer
        pattern = r'''
            (?P<STRING>'[^']*'|"[^"]*")     |  # String literals
            (?P<NUMBER>-?\d+(?:\.\d+)?)     |  # Numbers
            (?P<IDENTIFIER>[a-zA-Z_][a-zA-Z0-9_]*) |  # Identifiers
            (?P<OPERATOR><=|>=|!=|<>|<|>|=) |  # Comparison operators
            (?P<ARROW>-->|<--|<->)          |  # Arrow patterns
            (?P<SYMBOL>[-\[\](){}:,.])      |  # Single character symbols
            (?P<WHITESPACE>\s+)                # Whitespace
        '''
        
        tokens = []
        for match in re.finditer(pattern, query, re.VERBOSE):
            kind = match.lastgroup
            value = match.group()
            
            if kind == 'WHITESPACE':
                continue  # Skip whitespace
            elif kind == 'STRING':
                # Remove quotes from string literals
                tokens.append(value[1:-1])
            else:
                tokens.append(value)
        
        return tokens
    
    def _peek(self) -> Optional[str]:
        """Peek at the current token without consuming it."""
        if self.position >= len(self.tokens):
            return None
        return self.tokens[self.position]
    
    def _advance(self) -> Optional[str]:
        """Consume and return the current token."""
        if self.position >= len(self.tokens):
            return None
        token = self.tokens[self.position]
        self.position += 1
        return token
    
    def _expect(self, expected: str) -> str:
        """Consume a token and verify it matches the expected value."""
        token = self._advance()
        if token is None:
            raise ParseError(f"Expected '{expected}' but reached end of input")
        if token.upper() != expected.upper():
            raise ParseError(f"Expected '{expected}' but got '{token}'")
        return token
    
    def _parse_match(self) -> MatchClause:
        """Parse a MATCH clause."""
        self._expect("MATCH")
        patterns = self._parse_path_patterns()
        return MatchClause(patterns)
    
    def _parse_optional_match(self) -> MatchClause:
        """Parse an OPTIONAL MATCH clause."""
        self._expect("OPTIONAL")
        self._expect("MATCH")
        patterns = self._parse_path_patterns()
        return MatchClause(patterns, optional=True)
    
    def _parse_create(self) -> CreateClause:
        """Parse a CREATE clause."""
        self._expect("CREATE")
        patterns = self._parse_path_patterns()
        return CreateClause(patterns)
    
    def _parse_return(self) -> ReturnClause:
        """Parse a RETURN clause."""
        self._expect("RETURN")
        
        distinct = False
        if self._peek() and self._peek().upper() == "DISTINCT":
            distinct = True
            self._advance()
        
        items = []
        while True:
            item = self._advance()
            if item is None:
                break
            items.append(item)
            
            if self._peek() == ",":
                self._advance()  # consume comma
            else:
                break
        
        limit = None
        if self._peek() and self._peek().upper() == "LIMIT":
            self._advance()  # consume LIMIT
            limit_token = self._advance()
            if limit_token and limit_token.isdigit():
                limit = int(limit_token)
        
        return ReturnClause(items, distinct, limit)
    
    def _parse_where(self) -> WhereClause:
        """Parse a WHERE clause."""
        self._expect("WHERE")
        conditions = []
        
        while True:
            # Parse condition: variable.property operator value
            var_prop = self._advance()
            if not var_prop:
                break
            
            # Split variable.property
            if "." in var_prop:
                var, prop = var_prop.split(".", 1)
                key = f"{var}.{prop}"
            else:
                key = var_prop
            
            operator = self._advance()
            if not operator:
                raise ParseError("Expected operator after property")
            
            value_token = self._advance()
            if not value_token:
                raise ParseError("Expected value after operator")
            
            # Try to convert to appropriate type
            try:
                if value_token.isdigit():
                    value = int(value_token)
                elif "." in value_token and value_token.replace(".", "").isdigit():
                    value = float(value_token)
                else:
                    value = value_token
            except:
                value = value_token
            
            conditions.append(Property(key, value, operator))
            
            # Check for AND
            if self._peek() and self._peek().upper() == "AND":
                self._advance()
            else:
                break
        
        return WhereClause(conditions)
    
    def _parse_set(self) -> SetClause:
        """Parse a SET clause."""
        self._expect("SET")
        assignments = []
        
        while True:
            key = self._advance()
            if not key:
                break
            
            self._expect("=")
            value_token = self._advance()
            
            # Convert value
            try:
                if value_token.isdigit():
                    value = int(value_token)
                elif "." in value_token and value_token.replace(".", "").isdigit():
                    value = float(value_token)
                else:
                    value = value_token
            except:
                value = value_token
            
            assignments.append(Property(key, value, "="))
            
            if self._peek() == ",":
                self._advance()
            else:
                break
        
        return SetClause(assignments)
    
    def _parse_delete(self) -> DeleteClause:
        """Parse a DELETE clause."""
        self._expect("DELETE")
        variables = []
        
        while True:
            var = self._advance()
            if not var:
                break
            variables.append(var)
            
            if self._peek() == ",":
                self._advance()
            else:
                break
        
        return DeleteClause(variables)
    
    def _parse_detach_delete(self) -> DeleteClause:
        """Parse a DETACH DELETE clause."""
        self._expect("DETACH")
        self._expect("DELETE")
        variables = []
        
        while True:
            var = self._advance()
            if not var:
                break
            variables.append(var)
            
            if self._peek() == ",":
                self._advance()
            else:
                break
        
        return DeleteClause(variables, detach=True)
    
    def _parse_path_patterns(self) -> List[PathPattern]:
        """Parse path patterns (nodes and edges)."""
        patterns = []
        current_elements = []
        
        while self.position < len(self.tokens):
            token = self._peek()
            
            if token == "(":
                # Node pattern
                node = self._parse_node_pattern()
                current_elements.append(node)
            elif token in ("-", "<"):
                # Edge pattern
                edge = self._parse_edge_pattern()
                current_elements.append(edge)
            elif token == ",":
                # End of current pattern
                if current_elements:
                    patterns.append(PathPattern(current_elements))
                    current_elements = []
                self._advance()
            else:
                # End of patterns
                break
        
        if current_elements:
            patterns.append(PathPattern(current_elements))
        
        return patterns
    
    def _parse_node_pattern(self) -> NodePattern:
        """Parse a node pattern: (variable:Label {prop: value})"""
        self._expect("(")
        
        variable = None
        labels = []
        properties = []
        
        while self._peek() != ")":
            token = self._advance()
            if not token:
                raise ParseError("Unclosed node pattern")
            
            if token.startswith(":") and len(token) > 1:
                # Label like :Person
                labels.append(token[1:])
            elif ":" in token and not variable:
                # Variable:Label like n:Person
                parts = token.split(":", 1)
                variable = parts[0]
                if parts[1]:  # If there's a label after the colon
                    labels.append(parts[1])
            elif token == "{":
                # Properties
                properties = self._parse_properties()
                self._expect("}")
            elif not variable and ":" not in token:
                # Just a variable
                variable = token
            elif token.startswith(":"):
                # Additional label
                labels.append(token[1:])
        
        self._expect(")")
        return NodePattern(variable, labels, properties)
    
    def _parse_edge_pattern(self) -> EdgePattern:
        """Parse an edge pattern: -[variable:TYPE {prop: value}]->"""
        direction = "outgoing"
        
        # Determine direction
        if self._peek() == "<":
            self._advance()
            self._expect("-")
            direction = "incoming"
        elif self._peek() == "-":
            self._advance()
        
        variable = None
        relationship_type = None
        properties = []
        
        if self._peek() == "[":
            self._advance()  # consume [
            
            while self._peek() != "]":
                token = self._advance()
                if not token:
                    raise ParseError("Unclosed edge pattern")
                
                if token.startswith(":") and len(token) > 1:
                    relationship_type = token[1:]
                elif ":" in token:
                    parts = token.split(":", 1)
                    variable = parts[0]
                    if parts[1]:
                        relationship_type = parts[1]
                elif token == "{":
                    properties = self._parse_properties()
                    self._expect("}")
                elif not variable:
                    variable = token
            
            self._expect("]")
            
            # Check for trailing arrow
            if self._peek() == "-" and direction != "incoming":
                self._advance()
                if self._peek() == ">":
                    self._advance()
                    direction = "outgoing"
                else:
                    direction = "undirected"
            elif self._peek() == ">":
                self._advance()
                direction = "outgoing"
            elif direction != "incoming":
                direction = "undirected"
        else:
            # Simple edge without brackets like ->, <-, --
            if self._peek() == ">":
                self._advance()
                direction = "outgoing"
            elif direction != "incoming":
                direction = "undirected"
        
        return EdgePattern(variable, relationship_type, properties, direction)
    
    def _parse_properties(self) -> List[Property]:
        """Parse property constraints: {key: value, key2: value2}"""
        properties = []
        
        while self._peek() != "}":
            key = self._advance()
            if not key:
                raise ParseError("Expected property key")
            
            self._expect(":")
            value_token = self._advance()
            
            # Convert value
            try:
                if value_token.isdigit():
                    value = int(value_token)
                elif "." in value_token and value_token.replace(".", "").isdigit():
                    value = float(value_token)
                else:
                    value = value_token
            except:
                value = value_token
            
            properties.append(Property(key, value))
            
            if self._peek() == ",":
                self._advance()
            elif self._peek() != "}":
                break
        
        return properties