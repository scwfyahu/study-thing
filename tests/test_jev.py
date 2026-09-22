"""Jev System One client — shape parsing + disabled-by-default guard."""
import pytest

from backend import jev


def test_disabled_without_key(monkeypatch):
    monkeypatch.delenv("STUDY_JEV_API_KEY", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert jev.available() is False
    with pytest.raises(RuntimeError):
        jev.decide("state", {"q": {"type": "noul", "instructions": "x"}})


def test_choice_parses_answers_map(monkeypatch):
    monkeypatch.setattr(jev, "_key", lambda: "k")
    monkeypatch.setattr(jev, "decide", lambda *a, **k: {
        "answers": {"notebook": {"choice": "12", "confidence": 0.93,
                                  "probabilities": {"12": 0.93, "0": 0.07}}}})
    r = jev.choice("transcript", "notebook", "which class?", {"12": "Chem"})
    assert r["choice"] == "12"
    assert r["confidence"] == pytest.approx(0.93)


def test_choice_parses_flat_response(monkeypatch):
    """Some early-access builds answer at top level instead of answers{}."""
    monkeypatch.setattr(jev, "_key", lambda: "k")
    monkeypatch.setattr(jev, "decide", lambda *a, **k: {
        "notebook": {"choice": "0", "confidence": 0.6}})
    r = jev.choice("t", "notebook", "which class?", {"0": "none"})
    assert r["choice"] == "0"


def test_noul_probability(monkeypatch):
    monkeypatch.setattr(jev, "_key", lambda: "k")
    monkeypatch.setattr(jev, "decide", lambda *a, **k: {
        "answers": {"has_announcement": {"noul": 0.87}}})
    assert jev.noul("block", "has_announcement", "announce?") == pytest.approx(0.87)


def test_noul_bad_shape_raises(monkeypatch):
    monkeypatch.setattr(jev, "_key", lambda: "k")
    monkeypatch.setattr(jev, "decide", lambda *a, **k: {"answers": {}})
    with pytest.raises(RuntimeError):
        jev.noul("block", "q", "?")


def test_classifier_zero_choice_is_none():
    """Escrow rule: Jev choice '0' must map to no-match, never a notebook."""
    from backend.classify import _resolve_id
    NB = [{"id": 12, "name": "Chem"}]
    assert _resolve_id("0", NB) is None
    assert _resolve_id("12", NB) == 12
