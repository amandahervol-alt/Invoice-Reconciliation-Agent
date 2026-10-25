import json
from types import SimpleNamespace
from unittest import mock

import pytest

from services import classifier
from services.classifier import classify_discrepancy
from services.reconciler import reconcile_invoice
from tests.conftest import make_invoice


@pytest.fixture
def price_discrepancy(pos):
    items = [("Ergonomic Mesh Chairs", 10, 175.00), ("Standing Desk Converters", 5, 200.00)]
    return reconcile_invoice(make_invoice("Acme Office Supplies Inc.", "INV-10092", "PO-8821", items), pos["PO-8821"])


@pytest.fixture
def perfect_match(pos):
    items = [("Ergonomic Mesh Chairs", 10, 150.00), ("Standing Desk Converters", 5, 200.00)]
    return reconcile_invoice(make_invoice("Acme Office Supplies Inc.", "INV-10088", "PO-8821", items), pos["PO-8821"])


def test_matched_invoice_is_auto_approved_without_calling_claude(perfect_match, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    with mock.patch.object(classifier, "Anthropic") as client:
        cls = classify_discrepancy(perfect_match)
    client.assert_not_called()
    assert cls.category == "PERFECT_MATCH"
    assert cls.severity == "NONE"
    assert "Auto-approve" in cls.recommended_action


@pytest.mark.parametrize("key", [None, "your_anthropic_api_key_here"])
def test_without_api_key_falls_back_to_manual_review(price_discrepancy, monkeypatch, key):
    if key is not None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", key)
    cls = classify_discrepancy(price_discrepancy)
    assert cls.category == "UNCLASSIFIED_DISCREPANCY"
    assert cls.severity == "HIGH"  # $250 is outside tolerance
    assert "Unit price variance" in cls.explanation
    assert "+250.00" in cls.slack_summary


def _fake_client(text):
    client = mock.Mock()
    client.messages.create.return_value = SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])
    return client


def test_claude_response_is_parsed_into_classification(price_discrepancy, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_MODEL", "test-model")
    payload = {
        "category": "PRICE_VARIANCE",
        "severity": "MEDIUM",
        "explanation": "Chairs billed at $175 vs $150.",
        "recommended_action": "Request credit memo.",
        "slack_summary": "Price variance on INV-10092",
    }
    fake = _fake_client("Here you go:\n```json\n" + json.dumps(payload) + "\n```")
    with mock.patch.object(classifier, "Anthropic", return_value=fake):
        cls = classify_discrepancy(price_discrepancy)

    assert cls.category == "PRICE_VARIANCE"
    assert cls.recommended_action == "Request credit memo."
    kwargs = fake.messages.create.call_args.kwargs
    assert kwargs["model"] == "test-model"
    assert "INV-10092" in kwargs["messages"][0]["content"]


def test_claude_failure_returns_flagged_fallback(price_discrepancy, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    fake = mock.Mock()
    fake.messages.create.side_effect = RuntimeError("network down")
    with mock.patch.object(classifier, "Anthropic", return_value=fake):
        cls = classify_discrepancy(price_discrepancy)
    assert cls.category == "DISCREPANCY_FLAGGED"
    assert cls.severity == "HIGH"


def test_unparseable_claude_response_returns_flagged_fallback(price_discrepancy, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    with mock.patch.object(classifier, "Anthropic", return_value=_fake_client("not json at all")):
        assert classify_discrepancy(price_discrepancy).category == "DISCREPANCY_FLAGGED"
