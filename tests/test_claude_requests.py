"""Request/response compatibility with current Claude models (claude-sonnet-5-5)."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from services import classifier, extractor
from services.claude_response import DEFAULT_MODEL, first_text, model_name
from services.reconciler import reconcile_invoice
from tests.conftest import ROOT, make_invoice

RETIRED_MODEL = "claude-3-7-sonnet-20250219"
INVOICE_JSON = {
    "vendor_name": "Acme Office Supplies Inc.",
    "invoice_number": "INV-10088",
    "po_number": "PO-8821",
    "line_items": [{"description": "Ergonomic Mesh Chairs", "quantity": 10, "unit_price": 150.0, "total_price": 1500.0}],
    "subtotal": 1500.0,
    "total_amount": 1500.0,
}


def _response(*blocks):
    return SimpleNamespace(content=[SimpleNamespace(**b) for b in blocks])


THINKING = {"type": "thinking", "thinking": "", "signature": "sig"}


def _client(response):
    client = mock.Mock()
    client.messages.create.return_value = response
    return client


# ---------- helpers ----------

def test_default_model_is_current_sonnet():
    assert DEFAULT_MODEL == "claude-sonnet-5-5"


@pytest.mark.parametrize("env, expected", [(None, "claude-sonnet-5-5"), ("", "claude-sonnet-5-5"), ("my-model", "my-model")])
def test_model_name_respects_env(monkeypatch, env, expected):
    if env is None:
        monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    else:
        monkeypatch.setenv("ANTHROPIC_MODEL", env)
    assert model_name() == expected


def test_first_text_skips_thinking_blocks():
    assert first_text(_response(THINKING, {"type": "text", "text": "  answer "})) == "answer"


def test_first_text_raises_without_text_block():
    with pytest.raises(ValueError, match="no text block"):
        first_text(_response(THINKING))


# ---------- extractor ----------

def test_extractor_parses_answer_after_thinking_block(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    fake = _client(_response(THINKING, {"type": "text", "text": json.dumps(INVOICE_JSON)}))
    with mock.patch.object(extractor, "Anthropic", return_value=fake):
        inv = extractor.extract_invoice_fields("INVOICE ...")

    assert inv.invoice_number == "INV-10088"
    kwargs = fake.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-sonnet-5-5"
    for param in ("temperature", "top_p", "top_k"):
        assert param not in kwargs
    assert kwargs["extra_body"] == {"output_config": {"effort": "low"}}
    assert kwargs["max_tokens"] >= 4096


def test_extractor_raises_clear_error_when_no_text_block(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    with mock.patch.object(extractor, "Anthropic", return_value=_client(_response(THINKING))):
        with pytest.raises(ValueError, match="no text block"):
            extractor.extract_invoice_fields("INVOICE ...")


def test_extractor_requires_api_key():
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        extractor.extract_invoice_fields("INVOICE ...")


# ---------- classifier ----------

def test_classifier_parses_answer_after_thinking_block(pos, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    items = [("Ergonomic Mesh Chairs", 10, 175.00), ("Standing Desk Converters", 5, 200.00)]
    result = reconcile_invoice(make_invoice("Acme Office Supplies Inc.", "INV-10092", "PO-8821", items), pos["PO-8821"])
    payload = {"category": "PRICE_VARIANCE", "severity": "MEDIUM", "explanation": "e",
               "recommended_action": "a", "slack_summary": "s"}
    fake = _client(_response(THINKING, {"type": "text", "text": json.dumps(payload)}))
    with mock.patch.object(classifier, "Anthropic", return_value=fake):
        assert classifier.classify_discrepancy(result).category == "PRICE_VARIANCE"
    assert "temperature" not in fake.messages.create.call_args.kwargs


# ---------- config and n8n workflow ----------

@pytest.mark.parametrize("path", [".env.example", "README.md", "invoice-reconciliation-agent.json"])
def test_no_retired_model_references(path):
    assert RETIRED_MODEL not in (ROOT / path).read_text(encoding="utf-8")


def test_n8n_workflow_is_compatible_with_current_models():
    workflow = json.loads((ROOT / "invoice-reconciliation-agent.json").read_text(encoding="utf-8"))
    claude_nodes = [n for n in workflow["nodes"] if "api.anthropic.com" in json.dumps(n.get("parameters", {}))]
    assert len(claude_nodes) == 2
    for node in claude_nodes:
        body = node["parameters"]["jsonBody"]
        assert '"model": "claude-sonnet-5-5"' in body
        assert "temperature" not in body
        assert '"effort": "low"' in body
    assert "content[0]" not in json.dumps(workflow)
