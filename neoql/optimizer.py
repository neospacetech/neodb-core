"""Semantics-preserving rules for lazy Selection plans."""

from collections.abc import Mapping
from dataclasses import dataclass, fields
from typing import Any

from .selection import (
    AlgebraPlan,
    FilterPlan,
    IndexLookupPlan,
    LimitPlan,
    OffsetPlan,
    PlanNode,
    ProjectionFieldPlan,
    ProjectionPlan,
    ReversePlan,
    SimilarityPlan,
    TraversalPlan,
    UniquePlan,
)


@dataclass(frozen=True, slots=True)
class OptimizationResult:
    logical: tuple[PlanNode, ...]
    optimized: tuple[PlanNode, ...]
    rules: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "logical": [_plan_to_dict(node) for node in self.logical],
            "optimized": [_plan_to_dict(node) for node in self.optimized],
            "rules": list(self.rules),
        }


def optimize_plan(plan: tuple[PlanNode, ...], source: Any) -> OptimizationResult:
    optimized = list(plan)
    applied: list[str] = []

    simplified: list[PlanNode] = []
    for node in optimized:
        if isinstance(node, OffsetPlan) and node.count == 0:
            applied.append("remove_zero_offset")
            continue
        if (
            isinstance(node, ReversePlan)
            and simplified
            and isinstance(simplified[-1], ReversePlan)
        ):
            simplified.pop()
            applied.append("remove_double_reverse")
            continue
        if (
            isinstance(node, LimitPlan)
            and simplified
            and isinstance(simplified[-1], LimitPlan)
        ):
            previous = simplified.pop()
            assert isinstance(previous, LimitPlan)
            simplified.append(LimitPlan(min(previous.count, node.count)))
            applied.append("merge_limits")
            continue
        if (
            isinstance(node, OffsetPlan)
            and simplified
            and isinstance(simplified[-1], OffsetPlan)
        ):
            previous = simplified.pop()
            assert isinstance(previous, OffsetPlan)
            simplified.append(OffsetPlan(previous.count + node.count))
            applied.append("merge_offsets")
            continue
        if isinstance(node, UniquePlan) and simplified and simplified[-1] == node:
            applied.append("remove_redundant_unique")
            continue
        if (
            isinstance(node, ProjectionPlan)
            and simplified
            and isinstance(simplified[-1], ProjectionPlan)
        ):
            previous = simplified[-1]
            assert isinstance(previous, ProjectionPlan)
            if set(node.fields) <= set(previous.fields):
                simplified[-1] = node
                applied.append("merge_projections")
                continue
        simplified.append(node)
    optimized = simplified

    for index in range(1, len(optimized)):
        node = optimized[index]
        previous = optimized[index - 1]
        if isinstance(node, FilterPlan) and isinstance(previous, ProjectionPlan):
            fields = _predicate_fields(node.predicate)
            if fields <= set(previous.fields):
                optimized[index - 1 : index + 1] = [node, previous]
                applied.append("predicate_pushdown")

    indexed_fields = {
        metadata.field
        for metadata in getattr(getattr(source, "schema", None), "indexes", ())
        if metadata.indexed
    }
    for index, node in enumerate(optimized):
        if not isinstance(node, FilterPlan):
            break
        predicate = node.predicate
        if (
            isinstance(predicate, Mapping)
            and predicate.get("op") == "="
            and predicate.get("field") in indexed_fields
        ):
            optimized[index] = IndexLookupPlan(
                str(predicate["field"]),
                predicate.get("value"),
                predicate,
            )
            applied.append("index_selection")

    pruned: list[PlanNode] = []
    index = 0
    while index < len(optimized):
        node = optimized[index]
        following = optimized[index + 1] if index + 1 < len(optimized) else None
        if isinstance(node, (SimilarityPlan, TraversalPlan)) and isinstance(
            following, LimitPlan
        ):
            pruned.extend((node, following))
            applied.append(
                "vector_limit_pruning"
                if isinstance(node, SimilarityPlan)
                else "graph_limit_pruning"
            )
            index += 2
            continue
        if isinstance(node, AlgebraPlan) and _statically_empty(node.other):
            if node.operation in {"product", "intersection"}:
                pruned.append(LimitPlan(0))
                applied.append("join_elimination")
                index += 1
                continue
        pruned.append(node)
        index += 1

    return OptimizationResult(plan, tuple(pruned), tuple(dict.fromkeys(applied)))


def _predicate_fields(predicate: Any) -> set[str]:
    if not isinstance(predicate, Mapping):
        return set()
    if "field" in predicate:
        return {str(predicate["field"])}
    fields = set()
    for key in ("and", "or"):
        for child in predicate.get(key, ()):
            fields.update(_predicate_fields(child))
    if "not" in predicate:
        fields.update(_predicate_fields(predicate["not"]))
    return fields


def _statically_empty(selection: Any) -> bool:
    return bool(
        selection.plan
        and isinstance(selection.plan[-1], LimitPlan)
        and selection.plan[-1].count == 0
    )


def _plan_to_dict(node: PlanNode) -> dict[str, Any]:
    if isinstance(node, AlgebraPlan):
        payload = {
            "operation": node.operation,
            "other": {
                "dataset": node.other.dataset,
                "plan_length": len(node.other.plan),
            },
        }
    else:
        payload = {
            field.name: _serialize(getattr(node, field.name)) for field in fields(node)
        }
    return {"node": type(node).__name__, **payload}


def _serialize(value: Any) -> Any:
    if isinstance(value, ProjectionFieldPlan):
        payload: dict[str, Any] = {
            "name": value.name,
            "children": [_serialize(child) for child in value.children],
        }
        if value.span is not None:
            payload["location"] = {
                "start": {
                    "line": value.span.start.line,
                    "column": value.span.start.column,
                },
                "end": {
                    "line": value.span.end.line,
                    "column": value.span.end.column,
                },
            }
        return payload
    if isinstance(value, Mapping):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_serialize(item) for item in value]
    return value
