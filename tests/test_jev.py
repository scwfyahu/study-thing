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


def test_decide_notebook_none_without_engines():
    from backend.classify import decide_notebook
    assert decide_notebook("t", [{"id": 1, "name": "X"}]) is None


def test_decide_notebook_uses_jev(monkeypatch):
    from backend import classify, jev, laya_client
    monkeypatch.setattr(jev, "available", lambda: True)
    monkeypatch.setattr(laya_client, "available", lambda: False)
    monkeypatch.setattr(jev, "choice",
                        lambda *a, **k: {"choice": "14", "confidence": 0.97})
    d = decide_notebook_helper(classify, "lecture", [{"id": 14, "name": "Kasaysayan"}])
    assert d["notebook_id"] == 14
    assert "Jev" in d["reason"] and d["confidence"] == 0.97


def decide_notebook_helper(classify, state, nbs):
    return classify.decide_notebook(state, nbs)


def test_decide_notebook_zero_is_none(monkeypatch):
    from backend import classify, jev, laya_client
    monkeypatch.setattr(laya_client, "available", lambda: False)
    monkeypatch.setattr(jev, "available", lambda: True)
    monkeypatch.setattr(jev, "choice",
                        lambda *a, **k: {"choice": "0", "confidence": 0.72})
    d = classify.decide_notebook("noise", [{"id": 14, "name": "Kasaysayan"}])
    assert d["notebook_id"] is None and d["confidence"] == 0.72


def test_decide_notebook_engine_error_returns_none(monkeypatch):
    from backend import classify, jev, laya_client
    monkeypatch.setattr(laya_client, "available", lambda: False)
    monkeypatch.setattr(jev, "available", lambda: True)
    def boom(*a, **k):
        raise RuntimeError("429")
    monkeypatch.setattr(jev, "choice", boom)
    assert classify.decide_notebook("t", [{"id": 1, "name": "X"}]) is None
