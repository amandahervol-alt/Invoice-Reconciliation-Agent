import pytest

from services.reconciler import load_purchase_orders_from_csv, reconcile_invoice
from tests.conftest import make_invoice

ACME = "Acme Office Supplies Inc."
ACME_ITEMS = [("Ergonomic Mesh Chairs", 10, 150.00), ("Standing Desk Converters", 5, 200.00)]


# ---------- PO database ----------

def test_loads_all_purchase_orders_with_totals(pos):
    assert set(pos) == {"PO-8821", "PO-9940", "PO-7712"}
    assert pos["PO-8821"].expected_total == 2500.00
    assert pos["PO-9940"].expected_total == 1400.00
    assert pos["PO-7712"].expected_total == 700.00
    assert len(pos["PO-8821"].line_items) == 2
    assert pos["PO-8821"].vendor_name == "Acme Office Supplies"


def test_missing_csv_returns_empty_database(tmp_path):
    assert load_purchase_orders_from_csv(str(tmp_path / "missing.csv")) == {}


def test_po_numbers_are_normalized_to_uppercase(tmp_path):
    csv = tmp_path / "pos.csv"
    csv.write_text("po_number,vendor_name,item_description,quantity,unit_price\n po-1 ,V,Item,2,5.00\n,V,Skipped,1,1\n")
    pos = load_purchase_orders_from_csv(str(csv))
    assert list(pos) == ["PO-1"]
    assert pos["PO-1"].expected_total == 10.00


# ---------- Reconciliation (original cases A-D) ----------

def test_case_a_perfect_match(pos):
    res = reconcile_invoice(make_invoice(ACME, "INV-10088", "PO-8821", ACME_ITEMS), pos["PO-8821"])
    assert res.status == "MATCHED"
    assert res.total_variance == 0.0
    assert res.within_tolerance
    assert res.flags == []


def test_case_b_price_discrepancy(pos):
    items = [("Ergonomic Mesh Chairs", 10, 175.00), ("Standing Desk Converters", 5, 200.00)]
    res = reconcile_invoice(make_invoice(ACME, "INV-10092", "PO-8821", items), pos["PO-8821"])
    assert res.status == "DISCREPANCY"
    assert res.total_variance == 250.00
    assert not res.within_tolerance
    assert any("Unit price variance" in f for f in res.flags)
    chairs = res.line_item_variances[0]
    assert chairs.price_diff == 25.00
    assert chairs.variance == 250.00


def test_case_c_quantity_discrepancy(pos):
    items = [("Cloud Server Hosting - Pro", 1, 1200.00), ("Database Backup Storage TB", 8, 50.00)]
    res = reconcile_invoice(make_invoice("CloudScale Tech Labs LLC", "CST-5501", "PO-9940", items), pos["PO-9940"])
    assert res.status == "DISCREPANCY"
    assert res.total_variance == 200.00  # PO had 4 TB ($200), invoiced 8 TB ($400)
    assert any("Quantity variance" in f for f in res.flags)
    assert res.line_item_variances[1].qty_diff == 4


def test_case_d_missing_po():
    inv = make_invoice("Mystery Marketing Consultants", "MMC-9002", "PO-9999-NOTFOUND", [("Consultation", 1, 3500.00)])
    res = reconcile_invoice(inv, None)
    assert res.status == "MISSING_PO"
    assert res.total_variance == 3500.00
    assert not res.within_tolerance


def test_invoice_without_po_number_is_missing_po(pos):
    res = reconcile_invoice(make_invoice(ACME, "INV-1", None, ACME_ITEMS), pos["PO-8821"])
    assert res.status == "MISSING_PO"


# ---------- Additional rules ----------

def test_vendor_mismatch_is_flagged(pos):
    res = reconcile_invoice(make_invoice("Totally Different Vendor", "INV-2", "PO-8821", ACME_ITEMS), pos["PO-8821"])
    assert res.status == "DISCREPANCY"
    assert any("Vendor name mismatch" in f for f in res.flags)


def test_unapproved_line_item_is_flagged(pos):
    items = ACME_ITEMS + [("Gold Plated Stapler", 1, 99.00)]
    res = reconcile_invoice(make_invoice(ACME, "INV-3", "PO-8821", items), pos["PO-8821"])
    assert res.status == "DISCREPANCY"
    assert any("Unapproved line item" in f and "Gold Plated Stapler" in f for f in res.flags)
    assert res.line_item_variances[-1].issue == "Item not found on authorized Purchase Order"


def test_po_item_omitted_from_invoice_is_flagged(pos):
    res = reconcile_invoice(make_invoice(ACME, "INV-4", "PO-8821", ACME_ITEMS[:1]), pos["PO-8821"])
    assert res.status == "DISCREPANCY"
    assert any("omitted from invoice" in f and "Standing Desk Converters" in f for f in res.flags)
    assert res.total_variance == -1000.00


@pytest.mark.parametrize(
    "total, within",
    [
        (2500.00 + 12.50, True),   # exactly 0.5% of $2500
        (2500.00 + 12.51, False),  # just over 0.5%
        (2500.00 - 12.50, True),   # under-billing within tolerance
    ],
)
def test_total_tolerance_is_half_a_percent(pos, total, within):
    res = reconcile_invoice(make_invoice(ACME, "INV-5", "PO-8821", ACME_ITEMS, total=total), pos["PO-8821"])
    assert res.within_tolerance is within
    assert res.status == ("MATCHED" if within else "DISCREPANCY")


def test_dollar_tolerance_floor_applies_to_small_pos(pos):
    po = pos["PO-7712"].model_copy(deep=True)
    po.expected_total = 20.00  # 0.5% would be $0.10, so the $0.50 floor applies
    po.line_items = []
    inv = make_invoice("Apex Logistics & Freight", "INV-6", "PO-7712", [], total=20.40)
    assert reconcile_invoice(inv, po).within_tolerance


# ---------- PO lookup normalization ----------

@pytest.mark.parametrize("po_number", ["PO-8821", "po-8821", "  Po-8821 "])
def test_find_purchase_order_is_case_and_whitespace_insensitive(pos, po_number):
    from services.reconciler import find_purchase_order
    assert find_purchase_order(pos, po_number).po_number == "PO-8821"


@pytest.mark.parametrize("po_number", [None, "", "   ", "PO-0000"])
def test_find_purchase_order_returns_none_when_absent(pos, po_number):
    from services.reconciler import find_purchase_order
    assert find_purchase_order(pos, po_number) is None


# ---------- Line-level issue notes ----------

def test_line_with_price_and_quantity_variance_keeps_both_issues(pos):
    items = [("Ergonomic Mesh Chairs", 12, 175.00), ("Standing Desk Converters", 5, 200.00)]
    res = reconcile_invoice(make_invoice(ACME, "INV-7", "PO-8821", items), pos["PO-8821"])
    chairs = res.line_item_variances[0]
    assert "Unit price variance" in chairs.issue
    assert "Quantity variance" in chairs.issue
    assert sum("Unit price variance" in f for f in res.flags) == 1
    assert sum("Quantity variance" in f for f in res.flags) == 1


def test_matching_line_has_no_issue(pos):
    res = reconcile_invoice(make_invoice(ACME, "INV-8", "PO-8821", ACME_ITEMS), pos["PO-8821"])
    assert all(v.issue is None for v in res.line_item_variances)
