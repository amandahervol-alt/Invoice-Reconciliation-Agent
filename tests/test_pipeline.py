import pytest

import agent
from agent import print_reconciliation_report, run_reconciliation_pipeline
from tests.conftest import SAMPLE_INVOICES, SAMPLES, make_invoice

EXPECTED = {
    "invoice_101_perfect_match.txt": ("MATCHED", 0.00, "APPROVED - 100% MATCH"),
    "invoice_102_price_mismatch.txt": ("DISCREPANCY", 250.00, "DISCREPANCY DETECTED"),
    "invoice_103_quantity_mismatch.txt": ("DISCREPANCY", 200.00, "DISCREPANCY DETECTED"),
    "invoice_104_missing_po.txt": ("MISSING_PO", 3500.00, "REJECTED - MISSING PO"),
}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_pipeline_on_each_sample_invoice(name, capsys):
    status, variance, badge = EXPECTED[name]
    result = run_reconciliation_pipeline(str(SAMPLES / name), mock_invoice=SAMPLE_INVOICES[name])

    assert result["reconciliation"].status == status
    assert result["reconciliation"].total_variance == variance
    assert result["classification"] is not None

    print_reconciliation_report(result)
    out = capsys.readouterr().out
    assert badge in out
    assert SAMPLE_INVOICES[name].invoice_number in out
    assert f"${variance:+.2f}" in out


def test_pipeline_matches_lowercase_po_number():
    inv = SAMPLE_INVOICES["invoice_101_perfect_match.txt"].model_copy(update={"po_number": "po-8821"})
    result = run_reconciliation_pipeline(str(SAMPLES / "invoice_101_perfect_match.txt"), mock_invoice=inv)
    assert result["purchase_order"].po_number == "PO-8821"
    assert result["reconciliation"].status == "MATCHED"


def test_pipeline_uses_claude_extraction_when_no_mock(monkeypatch):
    expected = SAMPLE_INVOICES["invoice_101_perfect_match.txt"]
    seen = {}

    def fake_extract(raw_text):
        seen["text"] = raw_text
        return expected

    monkeypatch.setattr(agent, "extract_invoice_fields", fake_extract)
    result = run_reconciliation_pipeline(str(SAMPLES / "invoice_101_perfect_match.txt"))
    assert "INV-10088" in seen["text"]
    assert result["reconciliation"].status == "MATCHED"


def test_cli_exits_nonzero_on_error(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["agent.py", "does/not/exist.txt"])
    with pytest.raises(SystemExit) as exc:
        agent.main()
    assert exc.value.code == 1
    assert "Reconciliation failed" in capsys.readouterr().err
