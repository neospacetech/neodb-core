"""Tests for NeoQL parser and AST."""

import pytest
from neodb.neoql.parser import NeoQLParser, ParseError
from neodb.neoql.ast import (
    Query, MatchClause, CreateClause, ReturnClause, WhereClause,
    NodePattern, EdgePattern, PathPattern, Property
)


class TestNeoQLParser:
    """Test NeoQL parser."""
    
    def test_parse_simple_match(self):
        """Test parsing simple MATCH query."""
        parser = NeoQLParser()
        query = parser.parse("MATCH (n) RETURN n")
        
        assert isinstance(query, Query)
        assert len(query.clauses) == 2
        
        match_clause = query.clauses[0]
        assert isinstance(match_clause, MatchClause)
        assert len(match_clause.patterns) == 1
        
        return_clause = query.clauses[1]
        assert isinstance(return_clause, ReturnClause)
        assert "n" in return_clause.items
    
    def test_parse_match_with_label(self):
        """Test parsing MATCH with node labels."""
        parser = NeoQLParser()
        query = parser.parse("MATCH (n:Person) RETURN n")
        
        match_clause = query.clauses[0]
        pattern = match_clause.patterns[0]
        node = pattern.elements[0]
        
        assert isinstance(node, NodePattern)
        assert node.variable == "n"
        assert "Person" in node.labels
    
    def test_parse_match_with_properties(self):
        """Test parsing MATCH with node properties."""
        parser = NeoQLParser()
        query = parser.parse("MATCH (n:Person {name: John, age: 30}) RETURN n")
        
        match_clause = query.clauses[0]
        pattern = match_clause.patterns[0]
        node = pattern.elements[0]
        
        assert isinstance(node, NodePattern)
        assert len(node.properties) == 2
        
        prop_names = [p.key for p in node.properties]
        assert "name" in prop_names
        assert "age" in prop_names
    
    def test_parse_match_with_edge(self):
        """Test parsing MATCH with edges."""
        parser = NeoQLParser()
        query = parser.parse("MATCH (n)-[r:KNOWS]->(m) RETURN n, r, m")
        
        match_clause = query.clauses[0]
        pattern = match_clause.patterns[0]
        
        assert len(pattern.elements) == 3  # node, edge, node
        
        node1 = pattern.elements[0]
        edge = pattern.elements[1]
        node2 = pattern.elements[2]
        
        assert isinstance(node1, NodePattern)
        assert isinstance(edge, EdgePattern)
        assert isinstance(node2, NodePattern)
        
        assert edge.variable == "r"
        assert edge.relationship_type == "KNOWS"
        assert edge.direction == "outgoing"
    
    def test_parse_create_clause(self):
        """Test parsing CREATE clause."""
        parser = NeoQLParser()
        query = parser.parse("CREATE (n:Person {name: John})")
        
        assert len(query.clauses) == 1
        create_clause = query.clauses[0]
        assert isinstance(create_clause, CreateClause)
        
        pattern = create_clause.patterns[0]
        node = pattern.elements[0]
        assert isinstance(node, NodePattern)
        assert "Person" in node.labels
    
    def test_parse_return_with_limit(self):
        """Test parsing RETURN with LIMIT."""
        parser = NeoQLParser()
        query = parser.parse("MATCH (n) RETURN n LIMIT 10")
        
        return_clause = query.clauses[1]
        assert isinstance(return_clause, ReturnClause)
        assert return_clause.limit == 10
    
    def test_parse_return_distinct(self):
        """Test parsing RETURN DISTINCT."""
        parser = NeoQLParser()
        query = parser.parse("MATCH (n) RETURN DISTINCT n")
        
        return_clause = query.clauses[1]
        assert isinstance(return_clause, ReturnClause)
        assert return_clause.distinct is True
    
    def test_parse_where_clause(self):
        """Test parsing WHERE clause."""
        parser = NeoQLParser()
        query = parser.parse("MATCH (n) WHERE n.age > 18 RETURN n")
        
        assert len(query.clauses) == 3
        where_clause = query.clauses[1]
        assert isinstance(where_clause, WhereClause)
        
        assert len(where_clause.conditions) == 1
        condition = where_clause.conditions[0]
        assert condition.key == "n.age"
        assert condition.operator == ">"
        assert condition.value == 18
    
    def test_parse_optional_match(self):
        """Test parsing OPTIONAL MATCH."""
        parser = NeoQLParser()
        query = parser.parse("OPTIONAL MATCH (n)-[r]->(m) RETURN n, r, m")
        
        match_clause = query.clauses[0]
        assert isinstance(match_clause, MatchClause)
        assert match_clause.optional is True
    
    def test_parse_error_handling(self):
        """Test parse error handling."""
        parser = NeoQLParser()
        
        with pytest.raises(ParseError):
            parser.parse("INVALID QUERY SYNTAX")
    
    def test_tokenization(self):
        """Test query tokenization."""
        parser = NeoQLParser()
        
        # Test that tokenization works correctly
        tokens = parser._tokenize("MATCH (n:Person {name: 'John Doe'}) RETURN n")
        
        assert "MATCH" in tokens
        assert "(" in tokens
        assert "n" in tokens
        assert "Person" in tokens  # Label without colon
        assert "John Doe" in tokens  # String without quotes
        assert "RETURN" in tokens


class TestASTNodes:
    """Test AST node classes."""
    
    def test_node_pattern_str(self):
        """Test NodePattern string representation."""
        node = NodePattern(variable="n", labels=["Person"], 
                          properties=[Property("name", "John")])
        
        str_repr = str(node)
        assert "n" in str_repr
        assert "Person" in str_repr
        assert "name" in str_repr
    
    def test_edge_pattern_str(self):
        """Test EdgePattern string representation."""
        edge = EdgePattern(variable="r", relationship_type="KNOWS", 
                          direction="outgoing")
        
        str_repr = str(edge)
        assert "r" in str_repr
        assert "KNOWS" in str_repr
        assert "->" in str_repr
    
    def test_edge_pattern_directions(self):
        """Test different edge directions."""
        # Outgoing
        edge_out = EdgePattern(direction="outgoing")
        assert "->" in str(edge_out)
        
        # Incoming
        edge_in = EdgePattern(direction="incoming")
        assert "<-" in str(edge_in)
        
        # Undirected
        edge_undirected = EdgePattern(direction="undirected")
        str_repr = str(edge_undirected)
        assert "->" not in str_repr
        assert "<-" not in str_repr
    
    def test_query_get_clauses_by_type(self):
        """Test getting clauses by type from Query."""
        match_clause = MatchClause([])
        return_clause = ReturnClause([])
        
        query = Query([match_clause, return_clause])
        
        matches = query.get_clauses_by_type(MatchClause)
        assert len(matches) == 1
        assert matches[0] == match_clause
        
        returns = query.get_clauses_by_type(ReturnClause)
        assert len(returns) == 1
        assert returns[0] == return_clause
    
    def test_property_class(self):
        """Test Property class."""
        prop = Property("name", "John", "=")
        
        assert prop.key == "name"
        assert prop.value == "John"
        assert prop.operator == "="
    
    def test_path_pattern_str(self):
        """Test PathPattern string representation."""
        node1 = NodePattern("n")
        edge = EdgePattern("r", "KNOWS")
        node2 = NodePattern("m")
        
        path = PathPattern([node1, edge, node2])
        str_repr = str(path)
        
        # Should contain elements of all parts
        assert "(n)" in str_repr
        assert "KNOWS" in str_repr
        assert "(m)" in str_repr