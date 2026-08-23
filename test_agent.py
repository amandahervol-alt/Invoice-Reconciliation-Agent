import os
import sys

# Ensure UTF-8 output encoding if possible
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from services.parser import extract_invoice_text
from services.extractor import InvoiceData, LineItem
from services.reconciler import (
    load_purchase_orders_from_csv,
    reconcile_invoice,
    PurchaseOrder,
    POLineItem
)
from services.classifier import classify_discrepancy
from agent import print_reconciliation_report

def run_all_tests():
    print("=" * 60)
    print("TESTING INVOICE RECONCILIATION AGENT")
    print("=" * 60)

    # 1. Test Parser
    print("\n[1/4] Testing Parser on Sample Invoices...")
    sample_text = extract_invoice_text("data/sample_invoices/invoice_101_perfect_match.txt")
    assert "INV-10088" in sample_text
    assert "PO-8821" in sample_text
    print("  [OK] Text extraction verified.")

    # 2. Test PO Database Loading
    print("\n[2/4] Testing Purchase Order Database Load...")
    pos = load_purchase_orders_from_csv("data/purchase_orders.csv")
    assert "PO-8821" in pos, "PO-8821 not found in CSV"
    assert "PO-9940" in pos, "PO-9940 not found in CSV"
    po_8821 = pos["PO-8821"]
    assert po_8821.expected_total == 2500.00, f"Expected total $2500.00, got {po_8821.expected_total}"
    print(f"  [OK] Loaded {len(pos)} POs. PO-8821 total = ${po_8821.expected_total:.2f}")

    # 3. Test Pure Python Deterministic Reconciler
    print("\n[3/4] Testing Deterministic Reconciliation Engine...")

    # Case A: Perfect Match
    inv_perfect = InvoiceData(
        vendor_name="Acme Office Supplies Inc.",
        invoice_number="INV-10088",
        po_number="PO-8821",
        line_items=[
            LineItem(description="Ergonomic Mesh Chairs", quantity=10, unit_price=150.00, total_price=1500.00),
            LineItem(description="Standing Desk Converters", quantity=5, unit_price=200.00, total_price=1000.00)
        ],
        subtotal=2500.00,
        total_amount=2500.00
    )
    res_perfect = reconcile_invoice(inv_perfect, po_8821)
    assert res_perfect.status == "MATCHED", f"Expected MATCHED, got {res_perfect.status}"
    assert res_perfect.total_variance == 0.0, "Expected 0 variance"
    print("  [OK] Case A: Perfect Match passed (Status: MATCHED, Variance: $0.00)")

    # Case B: Price Inflation Discrepancy
    inv_price_diff = InvoiceData(
        vendor_name="Acme Office Supplies Inc.",
        invoice_number="INV-10092",
        po_number="PO-8821",
        line_items=[
            LineItem(description="Ergonomic Mesh Chairs", quantity=10, unit_price=175.00, total_price=1750.00),
            LineItem(description="Standing Desk Converters", quantity=5, unit_price=200.00, total_price=1000.00)
        ],
        subtotal=2750.00,
        total_amount=2750.00
    )
    res_price = reconcile_invoice(inv_price_diff, po_8821)
    assert res_price.status == "DISCREPANCY", f"Expected DISCREPANCY, got {res_price.status}"
    assert res_price.total_variance == 250.00, f"Expected $250.00, got {res_price.total_variance}"
    assert any("Unit price variance" in f for f in res_price.flags)
    print("  [OK] Case B: Price Discrepancy caught (Status: DISCREPANCY, Variance: +$250.00)")

    # Case C: Quantity Overcharge Discrepancy
    po_9940 = pos["PO-9940"]
    inv_qty_diff = InvoiceData(
        vendor_name="CloudScale Tech Labs LLC",
        invoice_number="CST-5501",
        po_number="PO-9940",
        line_items=[
            LineItem(description="Cloud Server Hosting - Pro", quantity=1, unit_price=1200.00, total_price=1200.00),
            LineItem(description="Database Backup Storage TB", quantity=8, unit_price=50.00, total_price=400.00)
        ],
        subtotal=1600.00,
        total_amount=1600.00
    )
    res_qty = reconcile_invoice(inv_qty_diff, po_9940)
    assert res_qty.status == "DISCREPANCY"
    assert res_qty.total_variance == 200.00  # PO had 4 TB ($200), invoiced 8 TB ($400)
    print("  [OK] Case C: Quantity Discrepancy caught (Status: DISCREPANCY, Variance: +$200.00)")

    # Case D: Missing PO
    inv_missing_po = InvoiceData(
        vendor_name="Mystery Marketing Consultants",
        invoice_number="MMC-9002",
        po_number="PO-9999-NOTFOUND",
        line_items=[LineItem(description="Consultation", quantity=1, unit_price=3500.00, total_price=3500.00)],
        subtotal=3500.00,
        total_amount=3500.00
    )
    res_missing = reconcile_invoice(inv_missing_po, None)
    assert res_missing.status == "MISSING_PO"
    print("  [OK] Case D: Missing PO caught (Status: MISSING_PO)")

    # 4. Test Classifier & Report Formatter
    print("\n[4/4] Testing Classifier & Audit Report Generation...")
    cls_report = classify_discrepancy(res_price)
    assert cls_report is not None
    print(f"  [OK] Classifier generated category: '{cls_report.category}'")
    print(f"  [OK] Recommended action: '{cls_report.recommended_action}'")

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED SUCCESSFULLY! The agent is fully functional.")
    print("=" * 60)

if __name__ == "__main__":
    run_all_tests()
