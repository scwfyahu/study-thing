"""Laya local decision engine — shape parsing + disabled guard."""
import pytest

from backend import laya_client


def test_disabled_by_env(monkeypatch):
    monkeypatch.setattr(laya_client, "DISABLED", True)
    assert laya_client.available() is False
    with pytest.raises(RuntimeError):
        laya_client.decide("s", {"q": {"type": "noul", "instructions": "x"}})


def test_choice_parses(monkeypatch):
    monkeypatch.setattr(laya_client, "_get_agent", lambda: None)
    monkeypatch.setattr(laya_client, "available", lambda: True)
    monkeypatch.setattr(laya_client, "decide", lambda *a, **k: {
        "answers": {"notebook": {"choice": "14", "confidence": 0.91,
                                  "probabilities": {"14": 0.91}}}})
    r = laya_client.choice("t", "notebook", "which?", {"14": "Kasaysayan"})
    assert r["choice"] == "14" and r["confidence"] == pytest.approx(0.91)


def test_choice_confidence_from_probs(monkeypatch):
    monkeypatch.setattr(laya_client, "decide", lambda *a, **k: {
        "answers": {"notebook": {"choice": "11", "probabilities": {"11": 0.77, "0": 0.23}}}})
    r = laya_client.choice("t", "notebook", "which?", {"11": "Chem"})
    assert r["confidence"] == pytest.approx(0.77)


def test_noul_parses(monkeypatch):
    monkeypatch.setattr(laya_client, "decide", lambda *a, **k: {
        "answers": {"has_announcement": {"noul": 0.62}}})
    assert laya_client.noul("b", "has_announcement", "?") == pytest.approx(0.62)


def test_noul_yes_true_probs(monkeypatch):
    monkeypatch.setattr(laya_client, "decide", lambda *a, **k: {
        "answers": {"q": {"probabilities": {"yes": 0.8, "no": 0.2}}}})
    assert laya_client.noul("b", "q", "?") == pytest.approx(0.8)


def test_bad_shape_raises(monkeypatch):
    monkeypatch.setattr(laya_client, "decide", lambda *a, **k: {"answers": {}})
    with pytest.raises(RuntimeError):
        laya_client.choice("t", "notebook", "which?", {})
