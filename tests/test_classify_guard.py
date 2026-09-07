"""Regression tests for the classifier id guard.

glm-5.3-flash used to return NULL for guided ["integer","null"] schemas and
string ids ("12") — the guard must coerce, drop sentinel 0, and drop unknown ids.
"""
from backend.classify import _resolve_id

NB = [{"id": 12, "name": "Chemistry 1"}, {"id": 35, "name": "Kasaysayan"}]


def test_string_id_coerced():
    assert _resolve_id("12", NB) == 12


def test_valid_int_passes():
    assert _resolve_id(35, NB) == 35


def test_zero_sentinel_is_no_match():
    assert _resolve_id(0, NB) is None


def test_unknown_id_dropped():
    assert _resolve_id(999, NB) is None
    assert _resolve_id("999", NB) is None


def test_none_stays_none():
    assert _resolve_id(None, NB) is None


def test_garbage_dropped():
    assert _resolve_id("abc", NB) is None
    assert _resolve_id(12.7, NB) == 12  # int() truncation is acceptable


def test_empty_notebooks_never_matches():
    assert _resolve_id("12", []) is None
