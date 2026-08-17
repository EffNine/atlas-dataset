import pytest


def test_validate_email_valid():
    from utils import validate_email
    assert validate_email("user@example.com") is True
    assert validate_email("a@b.c") is True


def test_validate_email_invalid():
    from utils import validate_email
    assert validate_email("invalid") is False
    assert validate_email("@no.com") is False
    assert validate_email("no@dot") is False
