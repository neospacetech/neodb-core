"""A simple NeoDB engine implementation."""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from datasets.document import DocumentDataset
from datasets.graph import GraphDataset
from datasets.kvs import KVSDataset
from datasets.table import TableDataset
from neoql.errors import (
    AmbiguousReferenceError,
    DatasetAlreadyExistsError,
    DatasetNotFoundError,
    EngineError,
    InvalidTraversalError,
    MissingReferenceError,
    ReferenceConflictError,
    ReferenceCycleError,
    ReferenceInUseError,
    UnsupportedDatasetError,
)
from neoql.predicates import validate_predicate
from neoql.references import (
    ReferenceValue,
    SelectionQueryValue,
    SelectionRecordsValue,
)
from neoql.selection import Selection
from neoql.types import TypeDescriptor, TypeKind, cast_value
from storage import StorageManager


@dataclass(slots=True)
class TransactionFrame:
    id: str
    datasets: dict[str, Any]


class NeoDBEngine:
    """A NeoDB engine for managing datasets."""

    def __init__(self, storage_path: str | Path | None = None):
        self._transactions: list[TransactionFrame] = []
        self._storage = (
            StorageManager(storage_path) if storage_path is not None else None
        )
        self._committed_datasets: dict[str, Any] = (
            self._storage.load() if self._storage is not None else {}
        )
        self._validate_loaded_state()

    @property
    def datasets(self) -> dict[str, Any]:
        """Return the datasets visible in the current transaction context."""
        if self._transactions:
            return self._transactions[-1].datasets
        return self._committed_datasets

    @property
    def transaction_depth(self) -> int:
        return len(self._transactions)

    @property
    def active_transaction_id(self) -> str | None:
        return self._transactions[-1].id if self._transactions else None

    def begin_transaction(self) -> str:
        transaction_id = str(uuid4())
        self._transactions.append(
            TransactionFrame(transaction_id, deepcopy(self.datasets))
        )
        return transaction_id

    def commit_transaction(self, transaction_id: str | None = None) -> str:
        frame = self._require_transaction(transaction_id)
        if len(self._transactions) > 1:
            self._transactions.pop()
            self._transactions[-1].datasets = frame.datasets
        else:
            if self._storage is not None:
                self._storage.persist(frame.datasets, frame.id)
            self._transactions.pop()
            self._committed_datasets = frame.datasets
        return frame.id

    def abort_transaction(self, transaction_id: str | None = None) -> str:
        frame = self._require_transaction(transaction_id)
        self._transactions.pop()
        return frame.id

    @contextmanager
    def transaction(self) -> Iterator[str]:
        """Run work in an atomic transaction or nested savepoint."""
        transaction_id = self.begin_transaction()
        try:
            yield transaction_id
        except Exception:
            if self.active_transaction_id == transaction_id:
                self.abort_transaction(transaction_id)
            raise
        else:
            if self.active_transaction_id == transaction_id:
                self.commit_transaction(transaction_id)

    def _require_transaction(
        self,
        transaction_id: str | None,
    ) -> TransactionFrame:
        if not self._transactions:
            raise EngineError(
                "no_active_transaction",
                "No transaction is active",
                details={},
            )
        frame = self._transactions[-1]
        if transaction_id is not None and transaction_id != frame.id:
            raise EngineError(
                "transaction_order",
                "Only the innermost active transaction can be completed",
                details={
                    "requested": transaction_id,
                    "active": frame.id,
                },
            )
        return frame

    def create_dataset(self, name, dtype="graph", schema=None):
        """Create a new dataset.

        Args:
            name (str): The name of the dataset.
            dtype (str, optional): The type of the dataset. Defaults to "graph".
            schema (dict, optional): The schema of the dataset. Defaults to None.

        Returns:
            Dataset: The created dataset object.
        """
        if name in self.datasets:
            raise DatasetAlreadyExistsError(name)
        dataset: Any
        if dtype == "graph":
            dataset = GraphDataset(name)
        elif dtype == "table":
            dataset = TableDataset(name=name, schema=schema)
        elif dtype == "document":
            dataset = DocumentDataset(name=name, schema=schema)
        elif dtype == "vector":
            dataset = DocumentDataset(name=name, schema=schema)
            dataset.storage_type = "vector"
        elif dtype in ("kv", "kvs"):
            dataset = KVSDataset(name)
        else:
            raise UnsupportedDatasetError(dtype)

        if isinstance(dataset, TableDataset):
            self._validate_reference_targets(dataset)
        self.datasets[name] = dataset
        return dataset

    def execute_query(self, query: Mapping[str, Any]):
        """Execute a query against a dataset.

        Args:
            dataset_name (str): The name of the dataset.
            query (dict): The query object.
        Returns:
            list: Query results.
        """
        if self.active_transaction_id is None and query.get("action") in {
            "create_dataset",
            "insert",
            "insert_selection",
            "update",
            "delete",
            "add_link",
        }:
            return self._execute_transaction([dict(query)])[0]
        initial_transaction = self.active_transaction_id
        try:
            return self._execute_query(query)
        except Exception:
            if (
                initial_transaction is not None
                and self.active_transaction_id == initial_transaction
            ):
                self.abort_transaction(initial_transaction)
            raise

    def _execute_query(self, query: Mapping[str, Any]):
        match query.get("action"):
            case "batch" | "transaction":
                return self._execute_transaction(query.get("queries", []))
            case "create_dataset":
                dataset = self.create_dataset(
                    query["name"],
                    dtype=query.get("type", "graph"),
                    schema=query.get("schema", None),
                )
                return {"status": "success", "dataset": dataset.name}
            case "add_link":
                return self._add_link(query)
            case "insert_selection":
                return self._insert_selection(query)

        dataset = self.datasets.get(query["dataset"])
        if not dataset:
            raise DatasetNotFoundError(query["dataset"])
        prepared = self._resolve_query_references(dataset, query)
        self._validate_mutation_references(dataset, prepared)
        if prepared.get("action") == "select":
            prepared = dict(prepared)
            prepared["_reference_resolver"] = self._resolve_projection_reference
        return dataset.query(prepared)

    def _resolve_projection_reference(
        self,
        reference: ReferenceValue,
    ) -> Mapping[str, Any]:
        target = self.datasets.get(reference.dataset)
        if target is None:
            raise DatasetNotFoundError(reference.dataset)
        matches = _find_reference_matches(target, reference.identity)
        if not matches:
            raise MissingReferenceError(
                reference.dataset,
                dict(reference.identity),
            )
        if len(matches) > 1:
            raise AmbiguousReferenceError(
                reference.dataset,
                dict(reference.identity),
            )
        return dict(matches[0])

    def _insert_selection(self, query: Mapping[str, Any]) -> Any:
        dataset_name = query.get("dataset")
        if not isinstance(dataset_name, str) or dataset_name not in self.datasets:
            raise DatasetNotFoundError(str(dataset_name))
        source_query = query.get("source")
        if not isinstance(source_query, Mapping):
            raise EngineError(
                "invalid_selection_insert",
                "Selection insertion requires a compiled source Selection",
                phase="compile",
            )
        source = self._execute_query(source_query)
        if not isinstance(source, Selection):
            raise EngineError(
                "invalid_selection_insert",
                "Selection insertion source must produce records",
                phase="plan",
            )
        records = source.consume()
        return self._execute_query(
            {
                "action": "insert",
                "dataset": dataset_name,
                "objects": records,
            }
        )

    def _add_link(self, query: Mapping[str, Any]) -> dict[str, Any]:
        source_query = query.get("source")
        target_query = query.get("target")
        if not isinstance(source_query, Mapping) or not isinstance(
            target_query,
            Mapping,
        ):
            raise InvalidTraversalError("Links require two endpoint selections")
        if source_query.get("dataset") != target_query.get("dataset"):
            raise InvalidTraversalError(
                "Link endpoints must belong to the same graph dataset",
            )
        dataset_name = source_query.get("dataset")
        if not isinstance(dataset_name, str):
            raise InvalidTraversalError("Link endpoint dataset must be named")
        dataset = self.datasets.get(dataset_name)
        if not isinstance(dataset, GraphDataset):
            raise InvalidTraversalError(
                "Link endpoints must belong to a graph dataset",
                dataset=dataset_name,
            )
        source_records = dataset.query(source_query).consume()
        target_records = dataset.query(target_query).consume()
        if len(source_records) != 1 or len(target_records) != 1:
            raise InvalidTraversalError(
                "Each link endpoint must select exactly one node",
                dataset=dataset_name,
                source_count=len(source_records),
                target_count=len(target_records),
            )
        properties = query.get("properties", {})
        if not isinstance(properties, Mapping):
            raise InvalidTraversalError("Link properties must be an object")
        unknown = set(properties) - {"label", "bidir", "data"}
        label = properties.get("label")
        bidirectional = properties.get("bidir", False)
        data = properties.get("data", {})
        if (
            unknown
            or not isinstance(label, str)
            or not label
            or not isinstance(bidirectional, bool)
            or not isinstance(data, Mapping)
        ):
            raise InvalidTraversalError(
                "Links require label, optional bidir boolean, and object data",
                fields=sorted(properties),
            )
        return {
            "status": "success",
            "link": dataset.add_link(
                source_records[0]["id"],
                target_records[0]["id"],
                label=label,
                bidirectional=bidirectional,
                data=data,
            ),
        }

    def _execute_transaction(
        self,
        queries: Any,
    ) -> list[Any]:
        if not isinstance(queries, list):
            raise EngineError(
                "invalid_transaction",
                "Transaction queries must be a list",
                phase="compile",
            )
        transaction_id = self.begin_transaction()
        try:
            results = [self._execute_query(query) for query in queries]
        except Exception:
            if self.active_transaction_id == transaction_id:
                self.abort_transaction(transaction_id)
            raise
        self.commit_transaction(transaction_id)
        return results

    def _validate_reference_targets(self, dataset: TableDataset) -> None:
        for field in dataset.schema.fields.values():
            for target_name in _reference_targets(field.type):
                target = (
                    dataset
                    if target_name == dataset.name
                    else self.datasets.get(target_name)
                )
                if target is None:
                    raise DatasetNotFoundError(target_name)
                if isinstance(target, TableDataset) and not _identity_fields(target):
                    raise AmbiguousReferenceError(target_name, "no identity constraint")

    def _validate_loaded_state(self) -> None:
        for dataset in self.datasets.values():
            if isinstance(dataset, TableDataset):
                try:
                    self._validate_reference_targets(dataset)
                except EngineError as error:
                    raise EngineError(
                        "storage_corruption",
                        "Persisted reference schema is invalid",
                        details={"dataset": dataset.name, "cause": error.code},
                    ) from error
                for record in dataset.rows:
                    for reference in _iter_references(record):
                        target = self.datasets.get(reference.dataset)
                        if target is None:
                            raise EngineError(
                                "storage_corruption",
                                "Persisted reference target is missing",
                                details={"dataset": reference.dataset},
                            )
                        try:
                            self._validate_reference_value(target, reference)
                        except EngineError as error:
                            raise EngineError(
                                "storage_corruption",
                                "Persisted reference is invalid",
                                details={
                                    "dataset": reference.dataset,
                                    "cause": error.code,
                                },
                            ) from error
            elif isinstance(dataset, GraphDataset):
                for edge in dataset.edges:
                    if (
                        edge.get("source") not in dataset.nodes
                        or edge.get("target") not in dataset.nodes
                    ):
                        raise EngineError(
                            "storage_corruption",
                            "Persisted graph link has a missing endpoint",
                            details={"dataset": dataset.name, "link": edge.get("id")},
                        )

    def _validate_mutation_references(
        self,
        dataset: Any,
        query: Mapping[str, Any],
    ) -> None:
        if not isinstance(dataset, TableDataset):
            return
        action = query.get("action")
        if action not in {"update", "delete"}:
            return
        filter_obj = query.get("filter")
        validate_predicate(filter_obj, dataset.schema)
        affected = [
            record
            for record in dataset.rows
            if not filter_obj or dataset._apply_filter(record, filter_obj)
        ]
        if not affected:
            return
        inbound = self._inbound_references(
            dataset,
            affected,
            ignore_affected_sources=action == "delete",
        )
        if action == "delete" and inbound:
            source_dataset, _reference, _record = inbound[0]
            raise ReferenceInUseError(dataset.name, source_dataset)
        if action == "update":
            changes = query.get("values", {})
            for source_dataset, reference, record in inbound:
                normalized = dataset.schema.normalize_update(record, changes)
                if any(
                    normalized[field] != value for field, value in reference.identity
                ):
                    raise ReferenceInUseError(dataset.name, source_dataset)

    def _inbound_references(
        self,
        target: TableDataset,
        affected: list[dict[str, Any]],
        *,
        ignore_affected_sources: bool,
    ) -> list[tuple[str, ReferenceValue, dict[str, Any]]]:
        inbound = []
        for source_name, source in self.datasets.items():
            if not isinstance(source, TableDataset):
                continue
            for source_record in source.rows:
                if (
                    ignore_affected_sources
                    and source is target
                    and source_record in affected
                ):
                    continue
                for reference in _iter_references(source_record):
                    if reference.dataset != target.name:
                        continue
                    matched = next(
                        (
                            record
                            for record in affected
                            if all(
                                record.get(field) == value
                                for field, value in reference.identity
                            )
                        ),
                        None,
                    )
                    if matched is not None:
                        inbound.append((source_name, reference, matched))
        return inbound

    def _resolve_query_references(
        self,
        dataset: Any,
        query: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if not isinstance(dataset, TableDataset):
            return query
        action = query.get("action")
        if action == "insert":
            prepared = dict(query)
            prepared["objects"] = [
                self._resolve_table_record(dataset, record, (), frozenset())
                for record in query.get("objects", [])
            ]
            return prepared
        if action == "update":
            prepared = dict(query)
            prepared["values"] = self._resolve_table_record(
                dataset,
                query.get("values", {}),
                (),
                frozenset(),
                partial=True,
            )
            return prepared
        return query

    def _resolve_table_record(
        self,
        dataset: TableDataset,
        record: Mapping[str, Any],
        path: tuple[str, ...],
        seen: frozenset[int],
        *,
        partial: bool = False,
    ) -> dict[str, Any]:
        prepared = dict(record)
        for field_name, value in record.items():
            field = dataset.schema.fields.get(field_name)
            if field is None:
                continue
            prepared[field_name] = self._resolve_typed_value(
                field.type,
                value,
                (*path, f"{dataset.name}.{field_name}"),
                seen,
            )
        return prepared

    def _resolve_typed_value(
        self,
        descriptor: TypeDescriptor,
        value: Any,
        path: tuple[str, ...],
        seen: frozenset[int],
    ) -> Any:
        value = self._materialize_selection_value(value)
        if descriptor.kind == TypeKind.NULLABLE:
            if value is None:
                return None
            wrapped = descriptor.arguments[0]
            assert isinstance(wrapped, TypeDescriptor)
            return self._resolve_typed_value(wrapped, value, path, seen)
        if descriptor.kind == TypeKind.REFERENCE:
            target = descriptor.arguments[0]
            assert isinstance(target, str)
            if isinstance(value, SelectionRecordsValue):
                records = self._selection_reference_records(value, target)
                if not records:
                    raise MissingReferenceError(
                        target,
                        {"selection_count": 0},
                    )
                if len(records) != 1:
                    raise AmbiguousReferenceError(
                        target,
                        {"selection_count": len(records)},
                    )
                value = records[0]
            return self._resolve_reference(target, value, path, seen)
        if descriptor.kind in {TypeKind.LIST, TypeKind.SET}:
            if isinstance(value, SelectionRecordsValue):
                member = descriptor.arguments[0]
                assert isinstance(member, TypeDescriptor)
                value = list(self._selection_records_for_descriptor(value, member))
            if not isinstance(value, (list, tuple, set, frozenset)):
                return value
            member = descriptor.arguments[0]
            assert isinstance(member, TypeDescriptor)
            resolved = [
                self._resolve_typed_value(member, item, path, seen) for item in value
            ]
            return resolved if descriptor.kind == TypeKind.LIST else set(resolved)
        if descriptor.kind == TypeKind.TUPLE:
            if isinstance(value, SelectionRecordsValue):
                for member in descriptor.arguments:
                    if isinstance(member, TypeDescriptor):
                        target = _descriptor_reference_target(member)
                        if target is not None and target != value.dataset:
                            raise ReferenceConflictError(target, ["dataset"])
                value = list(value.records)
            if not isinstance(value, (list, tuple)) or len(value) != len(
                descriptor.arguments
            ):
                return value
            return tuple(
                self._resolve_typed_value(member, item, path, seen)
                for member, item in zip(
                    descriptor.arguments,
                    value,
                    strict=True,
                )
                if isinstance(member, TypeDescriptor)
            )
        if descriptor.kind == TypeKind.MAP:
            if not isinstance(value, Mapping):
                return value
            key_type, value_type = descriptor.arguments
            assert isinstance(key_type, TypeDescriptor)
            assert isinstance(value_type, TypeDescriptor)
            return {
                self._resolve_typed_value(key_type, key, path, seen): (
                    self._resolve_typed_value(value_type, item, path, seen)
                )
                for key, item in value.items()
            }
        return value

    def _materialize_selection_value(self, value: Any) -> Any:
        if not isinstance(value, SelectionQueryValue):
            return value
        result = self._execute_query(value.query)
        if not isinstance(result, Selection):
            raise EngineError(
                "invalid_selection_value",
                "Selection value must produce records",
                phase="plan",
            )
        return SelectionRecordsValue(
            result.dataset,
            tuple(result.consume()),
        )

    def _selection_reference_records(
        self,
        value: SelectionRecordsValue,
        target: str,
    ) -> tuple[Mapping[str, Any], ...]:
        if value.dataset != target:
            raise ReferenceConflictError(target, ["dataset"])
        return value.records

    def _selection_records_for_descriptor(
        self,
        value: SelectionRecordsValue,
        descriptor: TypeDescriptor,
    ) -> tuple[Mapping[str, Any], ...]:
        target = _descriptor_reference_target(descriptor)
        if target is not None:
            return self._selection_reference_records(value, target)
        return value.records

    def _resolve_reference(
        self,
        target_name: str,
        value: Any,
        path: tuple[str, ...],
        seen: frozenset[int],
    ) -> ReferenceValue:
        target = self.datasets.get(target_name)
        if target is None:
            raise DatasetNotFoundError(target_name)
        if isinstance(value, ReferenceValue):
            if value.dataset != target_name:
                raise ReferenceConflictError(target_name, ["dataset"])
            return self._validate_reference_value(target, value)
        if isinstance(target, TableDataset):
            return self._resolve_table_reference(target, value, path, seen)
        if isinstance(target, GraphDataset):
            return self._resolve_graph_reference(target, value, path, seen)
        if isinstance(target, KVSDataset):
            return self._resolve_kvs_reference(target, value)
        raise AmbiguousReferenceError(target_name, value)

    def _validate_reference_value(
        self,
        target: Any,
        reference: ReferenceValue,
    ) -> ReferenceValue:
        identity = reference.identity
        if isinstance(target, TableDataset):
            try:
                identity = tuple(
                    (
                        field,
                        cast_value(value, target.schema.fields[field].type),
                    )
                    for field, value in identity
                )
            except KeyError as error:
                raise MissingReferenceError(
                    reference.dataset,
                    dict(reference.identity),
                ) from error
        matches = _find_reference_matches(target, identity)
        if not matches:
            raise MissingReferenceError(reference.dataset, dict(reference.identity))
        if len(matches) > 1:
            raise AmbiguousReferenceError(
                reference.dataset,
                dict(reference.identity),
            )
        return ReferenceValue(reference.dataset, identity)

    def _resolve_table_reference(
        self,
        target: TableDataset,
        value: Any,
        path: tuple[str, ...],
        seen: frozenset[int],
    ) -> ReferenceValue:
        identities = _identity_fields(target)
        if not identities:
            raise AmbiguousReferenceError(target.name, value)
        if not isinstance(value, Mapping):
            primary = target.schema.primary_key
            if len(primary) != 1:
                raise AmbiguousReferenceError(target.name, value)
            field_name = primary[0]
            field = target.schema.fields[field_name]
            casted = cast_value(value, field.type)
            identity = ((field_name, casted),)
            matches = _find_reference_matches(target, identity)
            if not matches:
                raise MissingReferenceError(target.name, value)
            return ReferenceValue(target.name, identity)

        marker = id(value)
        if marker in seen:
            raise ReferenceCycleError([*path, target.name])
        next_seen = seen | {marker}
        raw = dict(value)
        candidate_identities = []
        for fields in identities:
            if all(field in raw for field in fields):
                candidate_identities.append(
                    tuple(
                        (
                            field,
                            cast_value(raw[field], target.schema.fields[field].type),
                        )
                        for field in fields
                    )
                )
        if not candidate_identities:
            raise AmbiguousReferenceError(target.name, raw)

        matched_indexes = {
            index
            for identity in candidate_identities
            for index, _record in _find_table_matches(target, identity)
        }
        if len(matched_indexes) > 1:
            raise AmbiguousReferenceError(target.name, raw)
        prepared = self._resolve_table_record(
            target,
            raw,
            (*path, target.name),
            next_seen,
        )
        if matched_indexes:
            record = target.rows[next(iter(matched_indexes))]
            conflicts = sorted(
                field
                for field, item in prepared.items()
                if field in record and record[field] != item
            )
            if conflicts:
                raise ReferenceConflictError(target.name, conflicts)
            return ReferenceValue(target.name, _canonical_identity(target, record))

        inserted = target.insert(prepared)
        return ReferenceValue(target.name, _canonical_identity(target, inserted))

    def _resolve_graph_reference(
        self,
        target: GraphDataset,
        value: Any,
        path: tuple[str, ...],
        seen: frozenset[int],
    ) -> ReferenceValue:
        if isinstance(value, Mapping):
            marker = id(value)
            if marker in seen:
                raise ReferenceCycleError([*path, target.name])
            record = dict(value)
            if "id" not in record:
                raise AmbiguousReferenceError(target.name, record)
            identity = (("id", record["id"]),)
            existing = target.nodes.get(record["id"])
            if existing is not None:
                conflicts = sorted(
                    field
                    for field, item in record.items()
                    if field in existing and existing[field] != item
                )
                if conflicts:
                    raise ReferenceConflictError(target.name, conflicts)
            else:
                target.insert(record)
            return ReferenceValue(target.name, identity)
        if value not in target.nodes:
            raise MissingReferenceError(target.name, value)
        return ReferenceValue(target.name, (("id", value),))

    def _resolve_kvs_reference(
        self,
        target: KVSDataset,
        value: Any,
    ) -> ReferenceValue:
        if isinstance(value, Mapping):
            if "key" not in value:
                raise AmbiguousReferenceError(target.name, dict(value))
            key = value["key"]
            if key in target.store and target.store[key] != value.get("value"):
                raise ReferenceConflictError(target.name, ["value"])
            if key not in target.store:
                target.insert(dict(value))
        else:
            key = value
            if key not in target.store:
                raise MissingReferenceError(target.name, key)
        return ReferenceValue(target.name, (("key", key),))


def _reference_targets(descriptor: TypeDescriptor) -> list[str]:
    if descriptor.kind == TypeKind.REFERENCE:
        target = descriptor.arguments[0]
        assert isinstance(target, str)
        return [target]
    return [
        target
        for argument in descriptor.arguments
        if isinstance(argument, TypeDescriptor)
        for target in _reference_targets(argument)
    ]


def _descriptor_reference_target(descriptor: TypeDescriptor) -> str | None:
    current = descriptor
    while current.kind == TypeKind.NULLABLE:
        wrapped = current.arguments[0]
        assert isinstance(wrapped, TypeDescriptor)
        current = wrapped
    if current.kind != TypeKind.REFERENCE:
        return None
    target = current.arguments[0]
    assert isinstance(target, str)
    return target


def _iter_references(value: Any) -> Iterator[ReferenceValue]:
    if isinstance(value, ReferenceValue):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _iter_references(item)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from _iter_references(item)


def _identity_fields(dataset: TableDataset) -> list[tuple[str, ...]]:
    identities = []
    if dataset.schema.primary_key:
        identities.append(dataset.schema.primary_key)
    identities.extend(
        (name,)
        for name, field in dataset.schema.fields.items()
        if "unique" in field.constraints and "pk" not in field.constraints
    )
    return identities


def _canonical_identity(
    dataset: TableDataset,
    record: Mapping[str, Any],
) -> tuple[tuple[str, Any], ...]:
    fields = _identity_fields(dataset)[0]
    return tuple((field, record[field]) for field in fields)


def _find_table_matches(
    dataset: TableDataset,
    identity: tuple[tuple[str, Any], ...],
) -> list[tuple[int, Mapping[str, Any]]]:
    return [
        (index, record)
        for index, record in enumerate(dataset.rows)
        if all(record.get(field) == value for field, value in identity)
    ]


def _find_reference_matches(
    dataset: Any,
    identity: tuple[tuple[str, Any], ...],
) -> list[Mapping[str, Any]]:
    if isinstance(dataset, TableDataset):
        return [record for _index, record in _find_table_matches(dataset, identity)]
    identity_map = dict(identity)
    if isinstance(dataset, GraphDataset):
        record = dataset.nodes.get(identity_map.get("id"))
        return [record] if record is not None else []
    if isinstance(dataset, KVSDataset):
        key = identity_map.get("key")
        return (
            [{"key": key, "value": dataset.store[key]}] if key in dataset.store else []
        )
    return []
