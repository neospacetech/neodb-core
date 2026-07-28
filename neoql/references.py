"""Typed dataset reference values."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ReferenceValue:
    """A reference to one record, identified by stable identity fields."""

    dataset: str
    identity: tuple[tuple[str, Any], ...]

    def __post_init__(self) -> None:
        if not self.dataset or not self.identity:
            raise ValueError("References require a dataset and identity")

    def to_dict(self) -> dict[str, Any]:
        return {
            "$ref": self.dataset,
            "identity": dict(self.identity),
        }

    def __str__(self) -> str:
        identity = ", ".join(f"{field}={value!r}" for field, value in self.identity)
        return f"{self.dataset}({identity})"
