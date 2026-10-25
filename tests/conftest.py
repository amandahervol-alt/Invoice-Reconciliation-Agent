import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.extractor import InvoiceData, LineItem  # noqa: E402
from services.reconciler import load_purchase_orders_from_csv  # noqa: E402

PO_CSV = ROOT / "data" / "purchase_orders.csv"
SAMPLES = ROOT / "data" / "sample_invoices"


@pytest.fixture(autouse=True)
def _repo_root_and_no_api_key(monkeypatch):
    """Run every test from the repo root (data paths are relative) with no real Claude key."""
    monkeypatch.chdir(ROOT)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


@pytest.fixture
def pos():
    return load_purchase_orders_from_csv(str(PO_CSV))


def make_invoice(vendor, number, po, items, total=None, **kwargs):
    line_items = [LineItem(description=d, quantity=q, unit_price=p, total_price=q * p) for d, q, p in items]
    subtotal = sum(li.total_price for li in line_items)
    return InvoiceData(
        vendor_name=vendor,
        invoice_number=number,
        po_number=po,
        line_items=line_items,
        subtotal=subtotal,
        total_amount=subtotal if total is None else total,
        **kwargs,
    )


# Structured equivalents of the four sample invoice files (what Claude would extract).
SAMPLE_INVOICES = {
    "invoice_101_perfect_match.txt": make_invoice(
        "Acme Office Supplies Inc.", "INV-10088", "PO-8821",
        [("Ergonomic Mesh Chairs", 10, 150.00), ("Standing Desk Converters", 5, 200.00)],
    ),
    "invoice_102_price_mismatch.txt": make_invoice(
        "Acme Office Supplies Inc.", "INV-10092", "PO-8821",
        [("Ergonomic Mesh Chairs", 10, 175.00), ("Standing Desk Converters", 5, 200.00)],
    ),
    "invoice_103_quantity_mismatch.txt": make_invoice(
        "CloudScale Tech Labs LLC", "CST-5501", "PO-9940",
        [("Cloud Server Hosting - Pro", 1, 1200.00), ("Database Backup Storage TB", 8, 50.00)],
    ),
    "invoice_104_missing_po.txt": make_invoice(
        "Mystery Marketing Consultants", "MMC-9002", "PO-9999-NOTFOUND",
        [("Ad Campaign Strategy Consultation", 1, 3500.00)],
    ),
}
