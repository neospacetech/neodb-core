# Contributing to NeoDB Core

NeoDB Core is in its pre-alpha language and engine phase. Work is tracked on
the [NeoDB Core Roadmap](https://github.com/orgs/neospacetech/projects/3).

## Development setup

NeoDB supports Python 3.10 through 3.14.

```bash
git clone https://github.com/neospacetech/neodb-core.git
cd neodb-core
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Run the same gates used by CI:

```bash
ruff format --check .
ruff check .
mypy cli datasets engine.py
coverage run -m unittest discover -v
coverage report
python -m build
```

Use `ruff format .` to apply formatting before committing.

## Workflow

1. Choose a `Ready` issue from the project board and move it to `In progress`.
2. Create a focused branch from `main`.
3. Add tests for behavior changes and keep coverage at or above 70%.
4. Open a pull request that includes `Closes #N` for the relevant issue.
5. Move the issue to `In review`; it moves to `Done` after the change lands and
   all acceptance criteria have been verified.

Open a new issue when work reveals missing behavior that is not part of the
active issue's acceptance criteria. Include a concrete outcome and testable
acceptance criteria.

## Release process

NeoDB uses semantic versions. Until `1.0`, minor versions may introduce breaking
language or storage changes.

1. Confirm the target milestone has no open issues.
2. Update the version in `pyproject.toml` and document notable changes.
3. Run every local quality gate and verify CI on all supported Python versions.
4. Build with `python -m build` and inspect both wheel and source distribution.
5. Tag the release as `vX.Y.Z` and create GitHub release notes from the milestone.

Package publication is intentionally deferred until a registry and release
credentials are configured.
