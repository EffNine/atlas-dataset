import pytest


def test_increment():
    from app import Counter
    c = Counter()
    c.increment()
    assert c.get_value() == 1


def test_get_value_initial():
    from app import Counter
    c = Counter()
    assert c.get_value() == 0


def test_decrement():
    from app import Counter
    c = Counter()
    c.increment()
    c.increment()
    c.decrement()
    assert c.get_value() == 1


def test_reset():
    from app import Counter
    c = Counter()
    c.increment()
    c.increment()
    c.reset()
    assert c.get_value() == 0


def test_no_negative():
    from app import Counter
    c = Counter()
    c.decrement()
    assert c.get_value() == 0
