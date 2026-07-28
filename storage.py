"""Versioned snapshots, write-ahead logging, and state recovery."""

import base64
import json
import os
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID

from datasets.document import DocumentDataset
from datasets.graph import GraphDataset
from datasets.kvs import KVSDataset
from datasets.table import TableDataset
from neoql.errors import EngineError
from neoql.references import ReferenceValue

FORMAT = "neodb-core"
FORMAT_VERSION = 1


class StorageManager:
    """Persist complete committed engine states with WAL crash recovery."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.snapshot_path = self.path / "snapshot.json"
        self.wal_path = self.path / "wal.jsonl"
        try:
            self.path.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise _storage_error(
                "storage_io", "Cannot create storage directory"
            ) from error

    def load(self) -> dict[str, Any]:
        wal_states = self._read_wal()
        if wal_states:
            state = wal_states[-1]
            datasets = _decode_state(state)
            try:
                self._write_snapshot(state)
                self._clear_wal()
            except EngineError:
                pass
            return datasets
        if not self.snapshot_path.exists():
            return {}
        try:
            envelope = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise _storage_error(
                "storage_corruption",
                "Snapshot is unreadable",
            ) from error
        state = self._validate_envelope(envelope, source="snapshot")
        return _decode_state(state)

    def persist(self, datasets: Mapping[str, Any], transaction_id: str) -> None:
        state = _encode_state(datasets)
        record = self._envelope(state, transaction_id=transaction_id)
        self._append_wal(record)
        try:
            self._write_snapshot(state)
            self._clear_wal()
        except EngineError:
            # The fsynced WAL is the commit point. A failed checkpoint is safe:
            # startup will replay the latest complete WAL state.
            pass

    def _read_wal(self) -> list[dict[str, Any]]:
        if not self.wal_path.exists():
            return []
        try:
            content = self.wal_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise _storage_error("storage_corruption", "WAL is unreadable") from error
        lines = content.splitlines()
        states = []
        for index, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                envelope = json.loads(line)
            except json.JSONDecodeError as error:
                if index == len(lines) - 1:
                    self._clear_wal()
                    break
                raise _storage_error(
                    "storage_corruption",
                    "WAL contains an invalid record",
                ) from error
            states.append(self._validate_envelope(envelope, source="wal"))
        return states

    def _append_wal(self, envelope: Mapping[str, Any]) -> None:
        try:
            with self.wal_path.open("a", encoding="utf-8") as wal:
                wal.write(_canonical(envelope) + "\n")
                wal.flush()
                os.fsync(wal.fileno())
        except OSError as error:
            raise _storage_error("storage_io", "Cannot append the WAL") from error

    def _write_snapshot(self, state: Mapping[str, Any]) -> None:
        envelope = self._envelope(state)
        temporary = self.path / "snapshot.tmp"
        try:
            with temporary.open("w", encoding="utf-8") as snapshot:
                snapshot.write(_canonical(envelope) + "\n")
                snapshot.flush()
                os.fsync(snapshot.fileno())
            os.replace(temporary, self.snapshot_path)
            _fsync_directory(self.path)
        except OSError as error:
            raise _storage_error("storage_io", "Cannot publish the snapshot") from error

    def _clear_wal(self) -> None:
        temporary = self.path / "wal.tmp"
        try:
            with temporary.open("w", encoding="utf-8") as wal:
                wal.flush()
                os.fsync(wal.fileno())
            os.replace(temporary, self.wal_path)
            _fsync_directory(self.path)
        except OSError as error:
            raise _storage_error("storage_io", "Cannot checkpoint the WAL") from error

    def _envelope(
        self,
        state: Mapping[str, Any],
        *,
        transaction_id: str | None = None,
    ) -> dict[str, Any]:
        envelope = {
            "format": FORMAT,
            "version": FORMAT_VERSION,
            "checksum": sha256(_canonical(state).encode()).hexdigest(),
            "state": state,
        }
        if transaction_id is not None:
            envelope["transaction"] = transaction_id
        return envelope

    def _validate_envelope(
        self,
        envelope: Any,
        *,
        source: str,
    ) -> dict[str, Any]:
        if not isinstance(envelope, Mapping) or envelope.get("format") != FORMAT:
            raise _storage_error(
                "storage_corruption",
                f"Invalid {source} envelope",
            )
        if envelope.get("version") != FORMAT_VERSION:
            raise _storage_error(
                "storage_version",
                f"Unsupported {source} version",
            )
        state = envelope.get("state")
        if not isinstance(state, Mapping):
            raise _storage_error("storage_corruption", f"Invalid {source} state")
        checksum = sha256(_canonical(state).encode()).hexdigest()
        if checksum != envelope.get("checksum"):
            raise _storage_error(
                "storage_corruption",
                f"{source.capitalize()} checksum mismatch",
            )
        return dict(state)


def _encode_state(datasets: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "datasets": [
            _encode_dataset(name, dataset) for name, dataset in sorted(datasets.items())
        ]
    }


def _encode_dataset(name: str, dataset: Any) -> dict[str, Any]:
    storage_type = getattr(dataset, "storage_type", None)
    if isinstance(dataset, TableDataset):
        fields = []
        for field in dataset.schema.fields.values():
            constraints: list[Any] = []
            for constraint in sorted(field.constraints):
                if constraint == "default":
                    constraints.append(
                        {
                            "name": "default",
                            "arguments": [_encode_value(field.default)],
                        }
                    )
                elif constraint == "vector" and field.vector_dimension is not None:
                    constraints.append(
                        {
                            "name": "vector",
                            "arguments": [field.vector_dimension],
                        }
                    )
                else:
                    constraints.append(constraint)
            fields.append(
                {
                    "name": field.name,
                    "type": field.type.to_dict(),
                    "constraints": constraints,
                }
            )
        return {
            "name": name,
            "storage": storage_type,
            "schema": fields,
            "records": _encode_value(dataset.rows),
            "indexes": _encode_value(dataset.index_snapshot()),
        }
    if isinstance(dataset, GraphDataset):
        return {
            "name": name,
            "storage": "graph",
            "nodes": _encode_value(dataset.nodes),
            "edges": _encode_value(dataset.edges),
        }
    if isinstance(dataset, KVSDataset):
        return {
            "name": name,
            "storage": "kv",
            "records": _encode_value(dataset.store),
        }
    raise _storage_error(
        "storage_type",
        f"Dataset '{name}' cannot be persisted",
    )


def _decode_state(state: Mapping[str, Any]) -> dict[str, Any]:
    raw_datasets = state.get("datasets")
    if not isinstance(raw_datasets, list):
        raise _storage_error("storage_corruption", "Dataset list is invalid")
    datasets = {}
    for raw in raw_datasets:
        if not isinstance(raw, Mapping):
            raise _storage_error("storage_corruption", "Dataset entry is invalid")
        name = raw.get("name")
        storage_type = raw.get("storage")
        dataset: Any
        if not isinstance(name, str) or name in datasets:
            raise _storage_error("storage_corruption", "Dataset name is invalid")
        if storage_type in {"table", "document", "vector"}:
            schema = _decode_schema(raw.get("schema"))
            dataset = (
                TableDataset(name, schema)
                if storage_type == "table"
                else DocumentDataset(name, schema)
            )
            dataset.storage_type = storage_type
            records = _decode_value(raw.get("records"))
            if not isinstance(records, list):
                raise _storage_error("storage_corruption", "Table records are invalid")
            dataset.insert_many(records)
            persisted_indexes = _decode_value(raw.get("indexes"))
            if persisted_indexes != dataset.index_snapshot():
                raise _storage_error(
                    "storage_corruption",
                    f"Index state for '{name}' is inconsistent",
                )
        elif storage_type == "graph":
            dataset = GraphDataset(name)
            nodes = _decode_value(raw.get("nodes"))
            edges = _decode_value(raw.get("edges"))
            if not isinstance(nodes, dict) or not isinstance(edges, list):
                raise _storage_error("storage_corruption", "Graph state is invalid")
            dataset.nodes = nodes
            dataset.edges = edges
        elif storage_type == "kv":
            dataset = KVSDataset(name)
            records = _decode_value(raw.get("records"))
            if not isinstance(records, dict):
                raise _storage_error("storage_corruption", "Key/value state is invalid")
            dataset.store = records
        else:
            raise _storage_error(
                "storage_version",
                f"Unsupported dataset storage type '{storage_type}'",
            )
        datasets[name] = dataset
    return datasets


def _decode_schema(raw_schema: Any) -> dict[str, Any]:
    if not isinstance(raw_schema, list):
        raise _storage_error("storage_corruption", "Schema is invalid")
    schema = {}
    from neoql.types import TypeDescriptor

    for raw in raw_schema:
        if not isinstance(raw, Mapping) or not isinstance(raw.get("name"), str):
            raise _storage_error("storage_corruption", "Schema field is invalid")
        constraints = []
        for constraint in raw.get("constraints", []):
            if isinstance(constraint, Mapping):
                constraints.append(
                    {
                        "name": constraint.get("name"),
                        "arguments": [
                            _decode_value(argument)
                            for argument in constraint.get("arguments", [])
                        ],
                    }
                )
            else:
                constraints.append(constraint)
        schema[raw["name"]] = {
            "type": TypeDescriptor.from_dict(raw.get("type", {})),
            "constraints": constraints,
        }
    return schema


def _encode_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return {"$type": "decimal", "value": str(value)}
    if isinstance(value, datetime):
        return {"$type": "datetime", "value": value.isoformat()}
    if isinstance(value, date):
        return {"$type": "date", "value": value.isoformat()}
    if isinstance(value, time):
        return {"$type": "time", "value": value.isoformat()}
    if isinstance(value, timedelta):
        return {"$type": "duration", "value": value.total_seconds()}
    if isinstance(value, UUID):
        return {"$type": "uuid", "value": str(value)}
    if isinstance(value, bytes):
        return {"$type": "bytes", "value": base64.b64encode(value).decode()}
    if isinstance(value, ReferenceValue):
        return {
            "$type": "reference",
            "dataset": value.dataset,
            "identity": _encode_value(value.identity),
        }
    if isinstance(value, list):
        return {"$type": "list", "items": [_encode_value(item) for item in value]}
    if isinstance(value, tuple):
        return {"$type": "tuple", "items": [_encode_value(item) for item in value]}
    if isinstance(value, (set, frozenset)):
        return {
            "$type": "set",
            "items": sorted(
                (_encode_value(item) for item in value),
                key=_canonical,
            ),
        }
    if isinstance(value, Mapping):
        return {
            "$type": "map",
            "items": [
                [_encode_value(key), _encode_value(item)] for key, item in value.items()
            ],
        }
    raise _storage_error(
        "storage_value",
        f"Value of type {type(value).__name__} cannot be persisted",
    )


def _decode_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if not isinstance(value, Mapping):
        raise _storage_error("storage_corruption", "Encoded value is invalid")
    kind = value.get("$type")
    if kind == "decimal":
        return Decimal(value["value"])
    if kind == "datetime":
        return datetime.fromisoformat(value["value"])
    if kind == "date":
        return date.fromisoformat(value["value"])
    if kind == "time":
        return time.fromisoformat(value["value"])
    if kind == "duration":
        return timedelta(seconds=value["value"])
    if kind == "uuid":
        return UUID(value["value"])
    if kind == "bytes":
        return base64.b64decode(value["value"])
    if kind in {"list", "tuple", "set"}:
        items = [_decode_value(item) for item in value.get("items", [])]
        return (
            items if kind == "list" else tuple(items) if kind == "tuple" else set(items)
        )
    if kind == "map":
        return {
            _decode_value(key): _decode_value(item)
            for key, item in value.get("items", [])
        }
    if kind == "reference":
        identity = _decode_value(value.get("identity"))
        return ReferenceValue(value["dataset"], identity)
    raise _storage_error("storage_corruption", f"Unknown encoded value type '{kind}'")


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _storage_error(code: str, message: str) -> EngineError:
    return EngineError(code, message, details={})
