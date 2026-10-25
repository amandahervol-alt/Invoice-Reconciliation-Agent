import pytest
from fastapi.testclient import TestClient

from app import main as app_main
from tests.conftest import SAMPLE_INVOICES, SAMPLES


@pytest.fixture
def client():
    return TestClient(app_main.app)


def test_index_page_is_served(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "<html" in resp.text.lower()


def test_rejects_unsupported_file_types(client):
    resp = client.post("/api/reconcile", files={"file": ("invoice.csv", b"a,b", "text/csv")})
    assert resp.status_code == 400
    assert "Only .txt and .pdf" in resp.json()["detail"]


def test_requires_api_key(client):
    resp = client.post("/api/reconcile", files={"file": ("invoice.txt", b"INVOICE", "text/plain")})
    assert resp.status_code == 500
    assert "ANTHROPIC_API_KEY" in resp.json()["detail"]


@pytest.mark.parametrize(
    "name, status, classified",
    [
        ("invoice_101_perfect_match.txt", "MATCHED", False),
        ("invoice_102_price_mismatch.txt", "DISCREPANCY", True),
        ("invoice_104_missing_po.txt", "MISSING_PO", True),
    ],
)
def test_reconcile_endpoint_end_to_end(client, monkeypatch, name, status, classified):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "your_anthropic_api_key_here")  # classifier uses offline fallback
    monkeypatch.setattr(app_main, "extract_invoice_fields", lambda text: SAMPLE_INVOICES[name])

    content = (SAMPLES / name).read_bytes()
    resp = client.post("/api/reconcile", files={"file": (name, content, "text/plain")})

    assert resp.status_code == 200
    body = resp.json()
    assert body["invoice_data"]["invoice_number"] == SAMPLE_INVOICES[name].invoice_number
    assert body["reconciliation_result"]["status"] == status
    assert (body["classification"] is not None) is classified


@pytest.mark.parametrize("po_number", ["po-8821", " PO-8821 "])
def test_endpoint_matches_po_regardless_of_case_or_spacing(client, monkeypatch, po_number):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "your_anthropic_api_key_here")
    name = "invoice_101_perfect_match.txt"
    invoice = SAMPLE_INVOICES[name].model_copy(update={"po_number": po_number})
    monkeypatch.setattr(app_main, "extract_invoice_fields", lambda text: invoice)

    resp = client.post("/api/reconcile", files={"file": (name, (SAMPLES / name).read_bytes(), "text/plain")})

    assert resp.status_code == 200
    assert resp.json()["reconciliation_result"]["status"] == "MATCHED"
