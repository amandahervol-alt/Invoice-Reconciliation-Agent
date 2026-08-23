import csv
import os
from typing import Dict, List, Optional, Union
from pydantic import BaseModel
from services.extractor import InvoiceData, LineItem

class POLineItem(BaseModel):
    description: str
    quantity: float
    unit_price: float
    total_price: float

class PurchaseOrder(BaseModel):
    po_number: str
    vendor_name: str
    line_items: List[POLineItem] = []
    expected_total: float
    tax_expected: float = 0.0
    shipping_expected: float = 0.0
    status: str = "APPROVED"

class LineItemVariance(BaseModel):
    description: str
    invoice_qty: float
    po_qty: float
    qty_diff: float
    invoice_unit_price: float
    po_unit_price: float
    price_diff: float
    invoice_line_total: float
    po_line_total: float
    variance: float
    issue: Optional[str] = None

class ReconciliationResult(BaseModel):
    status: str  # "MATCHED", "DISCREPANCY", "MISSING_PO", "VENDOR_MISMATCH"
    invoice_number: str
    po_number: Optional[str]
    vendor_name: str
    invoice_total: float
    po_total: float
    total_variance: float
    within_tolerance: bool
    line_item_variances: List[LineItemVariance] = []
    flags: List[str] = []
    summary: str

def load_purchase_orders_from_csv(csv_path: str = "data/purchase_orders.csv") -> Dict[str, PurchaseOrder]:
    """
    Loads purchase orders from a local CSV database into a dictionary keyed by po_number.
    """
    if not os.path.exists(csv_path):
        return {}

    pos: Dict[str, PurchaseOrder] = {}
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            po_num = row.get("po_number", "").strip().upper()
            if not po_num:
                continue

            vendor = row.get("vendor_name", "").strip()
            desc = row.get("item_description", "").strip()
            qty = float(row.get("quantity", 0))
            price = float(row.get("unit_price", 0))
            line_total = qty * price
            
            line_item = POLineItem(
                description=desc,
                quantity=qty,
                unit_price=price,
                total_price=line_total
            )

            if po_num in pos:
                pos[po_num].line_items.append(line_item)
                pos[po_num].expected_total += line_total
            else:
                pos[po_num] = PurchaseOrder(
                    po_number=po_num,
                    vendor_name=vendor,
                    line_items=[line_item],
                    expected_total=line_total
                )
    return pos

def reconcile_invoice(
    invoice: InvoiceData,
    purchase_order: Optional[PurchaseOrder] = None,
    dollar_tolerance: float = 0.50,
    percent_tolerance: float = 0.005  # 0.5%
) -> ReconciliationResult:
    """
    Deterministic pure-Python reconciliation math engine.
    Compares invoice totals and line items against the authorized Purchase Order.
    """
    flags = []

    # 1. Missing PO Check
    if not invoice.po_number or not purchase_order:
        return ReconciliationResult(
            status="MISSING_PO",
            invoice_number=invoice.invoice_number,
            po_number=invoice.po_number,
            vendor_name=invoice.vendor_name,
            invoice_total=invoice.total_amount,
            po_total=0.0,
            total_variance=invoice.total_amount,
            within_tolerance=False,
            flags=["No approved Purchase Order found in system for this invoice."],
            summary=f"PO '{invoice.po_number}' could not be matched in the PO database."
        )

    # 2. Vendor Mismatch Check
    clean_inv_vendor = invoice.vendor_name.lower().replace(",", "").replace(".", "").strip()
    clean_po_vendor = purchase_order.vendor_name.lower().replace(",", "").replace(".", "").strip()
    if clean_inv_vendor not in clean_po_vendor and clean_po_vendor not in clean_inv_vendor:
        flags.append(f"Vendor name mismatch: Invoice has '{invoice.vendor_name}', PO has '{purchase_order.vendor_name}'")

    # 3. Line Item Level Cross-Checking
    line_variances: List[LineItemVariance] = []
    po_items_map = {item.description.lower().strip(): item for item in purchase_order.line_items}
    matched_po_keys = set()

    for inv_item in invoice.line_items:
        inv_desc_key = inv_item.description.lower().strip()
        
        # Best-effort matching by description
        matched_po_item = None
        for po_key, po_item in po_items_map.items():
            if po_key in inv_desc_key or inv_desc_key in po_key:
                matched_po_item = po_item
                matched_po_keys.add(po_key)
                break

        if matched_po_item:
            qty_diff = inv_item.quantity - matched_po_item.quantity
            price_diff = inv_item.unit_price - matched_po_item.unit_price
            variance = inv_item.total_price - matched_po_item.total_price
            
            issue = None
            if abs(price_diff) > 0.01:
                issue = f"Unit price variance: Invoiced ${inv_item.unit_price:.2f} vs PO ${matched_po_item.unit_price:.2f}"
                flags.append(issue)
            if abs(qty_diff) > 0.001:
                issue = f"Quantity variance: Invoiced {inv_item.quantity} vs PO {matched_po_item.quantity}"
                flags.append(issue)

            line_variances.append(LineItemVariance(
                description=inv_item.description,
                invoice_qty=inv_item.quantity,
                po_qty=matched_po_item.quantity,
                qty_diff=qty_diff,
                invoice_unit_price=inv_item.unit_price,
                po_unit_price=matched_po_item.unit_price,
                price_diff=price_diff,
                invoice_line_total=inv_item.total_price,
                po_line_total=matched_po_item.total_price,
                variance=variance,
                issue=issue
            ))
        else:
            # Invoiced item not on PO
            flags.append(f"Unapproved line item on invoice: '{inv_item.description}' (${inv_item.total_price:.2f})")
            line_variances.append(LineItemVariance(
                description=inv_item.description,
                invoice_qty=inv_item.quantity,
                po_qty=0.0,
                qty_diff=inv_item.quantity,
                invoice_unit_price=inv_item.unit_price,
                po_unit_price=0.0,
                price_diff=inv_item.unit_price,
                invoice_line_total=inv_item.total_price,
                po_line_total=0.0,
                variance=inv_item.total_price,
                issue="Item not found on authorized Purchase Order"
            ))

    # Check for PO items that were not billed
    for po_key, po_item in po_items_map.items():
        if po_key not in matched_po_keys:
            flags.append(f"PO item omitted from invoice: '{po_item.description}'")

    # 4. Total Calculation & Tolerance Check
    total_variance = round(invoice.total_amount - purchase_order.expected_total, 2)
    max_allowed_dollar_diff = max(dollar_tolerance, purchase_order.expected_total * percent_tolerance)
    within_tolerance = abs(total_variance) <= max_allowed_dollar_diff

    if len(flags) == 0 and within_tolerance:
        status = "MATCHED"
        summary = f"Invoice #{invoice.invoice_number} perfectly reconciles with PO #{purchase_order.po_number}."
    else:
        status = "DISCREPANCY"
        summary = f"Reconciliation discrepancy of ${total_variance:+.2f} on Invoice #{invoice.invoice_number} vs PO #{purchase_order.po_number}."

    return ReconciliationResult(
        status=status,
        invoice_number=invoice.invoice_number,
        po_number=purchase_order.po_number,
        vendor_name=invoice.vendor_name,
        invoice_total=invoice.total_amount,
        po_total=purchase_order.expected_total,
        total_variance=total_variance,
        within_tolerance=within_tolerance,
        line_item_variances=line_variances,
        flags=flags,
        summary=summary
    )
