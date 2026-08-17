# Repository fixtures for the EffNine Benchmark (EB) EXEC mode.

## What are fixtures?

Repository fixtures are self-contained codebases used by EXEC benchmark tasks.
Each fixture represents a small, deterministic project that the model must
modify, debug, or extend.

## Structure

```
repositories/<fixture-id>/
    README.md          — Human-readable description
    fixture.json       — Machine-readable manifest (required)
    source/            — Source code (copied into sandbox workspace)
    tests/             — Test suite (runs inside sandbox)
```

## Fixture manifest fields

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | Unique fixture identifier |
| `version` | No | Manifest version (default: 1.0) |
| `language` | No | Primary programming language |
| `framework` | No | Test/build framework |
| `image` | No | Docker image to use (default: python:3.11-slim) |
| `source_path` | No | Directory containing source code |
| `test_command` | Yes | Command to run tests (e.g. `pytest -q`) |
| `lint_command` | No | Linting command |
| `typecheck_command` | No | Type checking command |
| `timeout` | No | Max execution time in seconds |
| `expected_base_state` | No | Known initial state description |

## Design principles

1. **Deterministic**: Same fixture → same behavior every run
2. **Self-contained**: No external network or dependency downloads
3. **Small**: Fast to copy, build, and test
4. **Scoped**: One bug or feature per fixture
5. **Versioned**: Manifest includes version for compatibility tracking

## Adding a new fixture

1. Create directory: `repositories/<fixture-id>/`
2. Write `fixture.json` with required fields
3. Add source code under `source/`
4. Add tests under `tests/`
5. Write `README.md` describing the task
6. Test manually: `pytest -q` inside the fixture's `source/` dir
