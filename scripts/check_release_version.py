"""Validate that a release tag exactly matches the project version."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[import-not-found,no-redef]


def project_version(pyproject: Path) -> str:
    """Read the PEP 621 project version from a pyproject file."""
    with pyproject.open("rb") as source:
        payload = tomllib.load(source)
    version = payload.get("project", {}).get("version")
    if not isinstance(version, str) or not version:
        raise ValueError("pyproject.toml must define a non-empty project.version")
    return version


def validate_release_tag(tag: str, version: str) -> None:
    """Require the canonical v-prefixed tag for a project version."""
    expected = f"v{version}"
    if tag != expected:
        raise ValueError(
            f"Release tag '{tag}' does not match project version "
            f"'{version}'; expected '{expected}'"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tag", help="Git tag, including the leading 'v'")
    parser.add_argument(
        "--pyproject",
        type=Path,
        default=Path("pyproject.toml"),
        help="Path to pyproject.toml",
    )
    arguments = parser.parse_args(argv)
    try:
        validate_release_tag(
            arguments.tag,
            project_version(arguments.pyproject),
        )
    except (OSError, KeyError, tomllib.TOMLDecodeError, ValueError) as error:
        print(f"release version error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
