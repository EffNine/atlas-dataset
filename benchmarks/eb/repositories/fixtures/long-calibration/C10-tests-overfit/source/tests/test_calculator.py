import pytest


def test_add():
    from calculator import add
    assert add(2, 3) == 5


def test_add_negative():
    from calculator import add
    assert add(-1, -1) == -2
