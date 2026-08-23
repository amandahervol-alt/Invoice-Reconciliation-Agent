import os
import sys
import argparse
from typing import Optional
from tabulate import tabulate

from services.parser import extract_invoice_text
from services.extractor import extract_invoice_fields, InvoiceData
from services.reconciler import (
    load_purchase_orders_from_csv,
    reconcile_invoice,
    PurchaseOrder,
    ReconciliationResult
)
from services.classifier import classify_discrepancy, DiscrepancyClassification

def run_reconciliation_pipeline(
    invoice_path: str,
    po_database_path: str = "data/purchase_orders.csv",
    mock_invoice: Optional[InvoiceData] = None
) -> dict:
    """
    Executes the complete 7-step invoice reconciliation pipeline:
    1. Parse raw text from invoice document.
    2. Extract structured fields via Claude (or mock).
    3. Look up Purchase Order from database.
    4. Deterministic pure-Python comparison and tolerance checks.
    5. Classify discrepancy root-cause with Claude.
    6. Generate audit output.
    """
    print(f"\n[1/5] Extracting invoice text from: {invoice_path}")
    raw_text = extract_invoice_text(invoice_path)

    print("[2/5] Extracting structured invoice fields with Claude...")
    if mock_invoice:
        invoice_data = mock_invoice
    else:
        invoice_data = extract_invoice_fields(raw_text)

    print(f"  -> Vendor: {invoice_data.vendor_name}")
    print(f"  -> Invoice #: {invoice_data.invoice_number}")
    print(f"  -> PO #: {invoice_data.po_number or 'NOT SPECIFIED'}")
    print(f"  -> Total: ${invoice_data.total_amount:.2f}")

    print(f"[3/5] Looking up PO from '{po_database_path}'...")
    po_database = load_purchase_orders_from_csv(po_database_path)
    po_record = po_database.get(invoice_data.po_number.upper()) if invoice_data.po_number else None

    if po_record:
        print(f"  -> Found PO #{po_record.po_number} (Authorized Total: ${po_record.expected_total:.2f})")
    else:
        print(f"  -> WARNING: No matching PO found in database.")

    print("[4/5] Running deterministic reconciliation arithmetic...")
    recon_result = reconcile_invoice(invoice_data, po_record)

    print("[5/5] Classifying discrepancy root-cause...")
    classification = classify_discrepancy(recon_result)

    return {
        "invoice": invoice_data,
        "purchase_order": po_record,
        "reconciliation": recon_result,
        "classification": classification
    }

def print_reconciliation_report(result_payload: dict):
    """Prints a beautiful, auditable CLI report."""
    recon: ReconciliationResult = result_payload["reconciliation"]
    cls: DiscrepancyClassification = result_payload["classification"]
    inv: InvoiceData = result_payload["invoice"]

    print("\n" + "=" * 70)
    print("           INVOICE RECONCILIATION AUDIT REPORT")
    print("=" * 70)

    # Status Banner
    if recon.status == "MATCHED":
        status_badge = "[STATUS: APPROVED - 100% MATCH]"
    elif recon.status == "MISSING_PO":
        status_badge = "[STATUS: REJECTED - MISSING PO]"
    else:
        status_badge = f"[STATUS: DISCREPANCY DETECTED - {cls.category}]"

    print(f"\n{status_badge}")
    print(f"Vendor:        {inv.vendor_name}")
    print(f"Invoice #:     {inv.invoice_number}")
    print(f"PO #:          {recon.po_number or 'N/A'}")
    print(f"Invoice Total: ${recon.invoice_total:.2f}")
    print(f"PO Total:      ${recon.po_total:.2f}")
    print(f"Net Variance:  ${recon.total_variance:+.2f}")
    print(f"Tolerance:     {'WITHIN TOLERANCE' if recon.within_tolerance else 'EXCEEDS TOLERANCE'}")

    # Line Item Breakdown Table
    if recon.line_item_variances:
        print("\n--- Line Item Audit Breakdown ---")
        table_rows = []
        for item in recon.line_item_variances:
            table_rows.append([
                item.description[:30],
                f"{item.invoice_qty:.1f} (PO: {item.po_qty:.1f})",
                f"${item.invoice_unit_price:.2f} (PO: ${item.po_unit_price:.2f})",
                f"${item.invoice_line_total:.2f}",
                f"${item.variance:+.2f}",
                item.issue or "MATCH"
            ])
        headers = ["Item", "Qty (Inv/PO)", "Unit Price", "Inv Total", "Variance", "Audit Note"]
        print(tabulate(table_rows, headers=headers, tablefmt="rounded_grid"))

    # Root Cause & Bookkeeper Action
    print("\n--- AI Classification & Recommendation ---")
    print(f"Root Cause:     {cls.category} (Severity: {cls.severity})")
    print(f"Explanation:    {cls.explanation}")
    print(f"Action Needed:  {cls.recommended_action}")
    print(f"Slack Alert:    {cls.slack_summary}")
    print("=" * 70 + "\n")

def main():
    parser = argparse.ArgumentParser(description="Invoice Reconciliation Agent CLI")
    parser.add_argument("invoice_path", help="Path to invoice PDF or text file")
    parser.add_argument("--pos", default="data/purchase_orders.csv", help="Path to purchase orders CSV")
    args = parser.parse_args()

    try:
        result = run_reconciliation_pipeline(args.invoice_path, args.pos)
        print_reconciliation_report(result)
    except Exception as e:
        print(f"\n[ERROR] Reconciliation failed: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
