"""Tests for the CSV parser fixture."""
import pytest
import sys
from pathlib import Path

# Add source to path
sys.path.insert(0, str(Path(__file__).parent.parent / "source"))

from parser import CSVParser


SAMPLE_CSV = """name,age,city
Alice,30,NYC
Bob,25,LA
Charlie,35,Chicago
"""


def test_split_records_count():
    """After fix: should return ALL data rows, not skip the last one."""
    parser = CSVParser()
    records = parser.split_records(SAMPLE_CSV)
    assert len(records) == 3, f"Expected 3 records, got {len(records)}"


def test_split_records_content():
    """After fix: last record should be present."""
    parser = CSVParser()
    records = parser.split_records(SAMPLE_CSV)
    names = [r["name"] for r in records]
    assert "Charlie" in names, f"Missing 'Charlie' in {names}"


def test_split_records_headers():
    """Headers should be correct."""
    parser = CSVParser()
    records = parser.split_records(SAMPLE_CSV)
    assert list(records[0].keys()) == ["name", "age", "city"]


def test_empty_input():
    """Empty input should return empty list."""
    parser = CSVParser()
    assert parser.split_records("") == []


def test_single_row():
    """Single data row should work."""
    parser = CSVParser()
    records = parser.split_records("a,b\n1,2")
    assert len(records) == 1
    assert records[0] == {"a": "1", "b": "2"}
