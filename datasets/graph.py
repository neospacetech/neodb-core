from collections.abc import Mapping
from typing import Any

from neoql.errors import InvalidTraversalError
from neoql.selection import Selection, TraversalPlan

from .base import BaseDataset


class GraphDataset(BaseDataset):
    """A dataset representing a graph structure.

    Args:
        BaseDataset (BaseDataset): The base dataset class.
    """

    def __init__(self, name):
        self.name = name
        self.nodes = {}
        self.edges = []

    def insert(self, obj):
        node_id = obj.get("id")
        if node_id is None:
            raise InvalidTraversalError(
                "Graph nodes require an 'id'",
                dataset=self.name,
            )
        self.nodes[node_id] = obj

    def add_link(
        self,
        source: Any,
        target: Any,
        *,
        label: str,
        bidirectional: bool = False,
        data: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        edge = {
            "id": len(self.edges) + 1,
            "label": label,
            "source": source,
            "target": target,
            "bidir": bidirectional,
            "data": dict(data or {}),
        }
        self.edges.append(edge)
        return dict(edge)

    def query(self, neoql):
        # NeoQL: select, filter, order_by, limit, offset
        if neoql.get("action") == "insert":
            for obj in neoql["objects"]:
                self.insert(obj)
            return {
                "status": "success",
                "inserted_ids": [obj.get("id") for obj in neoql["objects"]],
            }
        return self._select(neoql)

    def _selection_records(self):
        return list(self.nodes.values())

    def _validate_selection(self, selection: Selection) -> None:
        for node in selection.plan:
            if isinstance(node, TraversalPlan) and not isinstance(node.label, str):
                raise InvalidTraversalError(
                    "Traversal relationship label must be a string",
                    dataset=self.name,
                )

    def _traverse_selection(
        self,
        records: list[dict[str, Any]],
        label: str,
        depth: int,
    ) -> list[dict[str, Any]]:
        frontier = [record.get("id") for record in records]
        if any(node_id not in self.nodes for node_id in frontier):
            raise InvalidTraversalError(
                "Traversal source contains a missing graph node",
                dataset=self.name,
            )
        visited = set(frontier)
        result = []
        for _level in range(depth):
            next_frontier = []
            for node_id in frontier:
                for edge in self.edges:
                    neighbor = None
                    if edge["label"] != label:
                        continue
                    if edge["source"] == node_id:
                        neighbor = edge["target"]
                    elif edge["bidir"] and edge["target"] == node_id:
                        neighbor = edge["source"]
                    if neighbor is None or neighbor in visited:
                        continue
                    if neighbor not in self.nodes:
                        raise InvalidTraversalError(
                            "Traversal link targets a missing graph node",
                            dataset=self.name,
                            node=neighbor,
                        )
                    visited.add(neighbor)
                    next_frontier.append(neighbor)
                    result.append(dict(self.nodes[neighbor]))
            frontier = next_frontier
            if not frontier:
                break
        return result


# Helper for filter logic
