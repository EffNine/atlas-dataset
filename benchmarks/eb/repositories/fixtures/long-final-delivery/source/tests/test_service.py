import pytest


def test_get_data():
    from service import DataService
    ds = DataService()
    result = ds.get_data()
    assert result == {"status": "ok"}
    assert result["status"] == "ok"


def test_is_healthy():
    from service import DataService
    ds = DataService()
    assert ds.is_healthy() is True
