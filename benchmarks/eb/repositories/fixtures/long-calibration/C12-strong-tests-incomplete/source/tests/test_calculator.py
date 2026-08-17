import pytest


def test_add():
    from calculator import add
    assert add(2, 3) == 5
    assert add(-1, 1) == 0
    assert add(0, 0) == 0


def test_subtract():
    from calculator import subtract
    assert subtract(5, 3) == 2
    assert subtract(0, 5) == -5
    assert subtract(0, 0) == 0


def test_multiply():
    from calculator import multiply
    assert multiply(3, 4) == 12
    assert multiply(0, 100) == 0
    assert multiply(-2, 3) == -6


def test_divide():
    from calculator import divide
    assert divide(10, 2) == 5.0
    assert divide(7, 2) == 3.5
    assert divide(0, 1) == 0.0


def test_divide_by_zero():
    from calculator import divide
    with pytest.raises(ValueError):
        divide(10, 0)


def test_divide_float_precision():
    from calculator import divide
    result = divide(1, 3)
    assert abs(result - 0.333333) < 0.0001
