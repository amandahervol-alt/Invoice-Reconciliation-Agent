import pytest

from services.parser import extract_invoice_text
from tests.conftest import SAMPLES


def test_extracts_text_from_sample_invoice_file():
    text = extract_invoice_text(str(SAMPLES / "invoice_101_perfect_match.txt"))
    assert "INV-10088" in text
    assert "PO-8821" in text
    assert "Total Amount Due: $2500.00" in text


@pytest.mark.parametrize("name", sorted(p.name for p in SAMPLES.glob("*.txt")))
def test_every_sample_invoice_has_number_and_po(name):
    text = extract_invoice_text(str(SAMPLES / name))
    assert "Invoice Number:" in text
    assert "Purchase Order #:" in text


def test_missing_file_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        extract_invoice_text(str(tmp_path / "nope.txt"))


def test_utf8_bytes_are_decoded():
    assert extract_invoice_text("Café invoice €10".encode("utf-8"), "inv.txt") == "Café invoice €10"


def test_non_utf8_bytes_fall_back_to_latin1():
    assert extract_invoice_text("Café".encode("latin-1"), "inv.txt") == "Café"


def test_invalid_source_type_raises_value_error():
    with pytest.raises(ValueError):
        extract_invoice_text(12345)
