# EB Python Bug Fix Fixture 001
# Fix the off-by-one bug in split_records()

## Repository
- Language: Python 3.11
- Framework: pytest
- Test command: pytest -q

## Known Bug
The `split_records()` method in `parser.py` has an off-by-one error:
it skips the last record when splitting CSV lines.

## Expected Fix
Change the range in the split loop to include the final element.

## Docker Compatibility
Uses python:3.11-slim image. No additional dependencies required.
