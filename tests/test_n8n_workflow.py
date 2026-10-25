"""Checks for the n8n workflow template (invoice-reconciliation-agent.json)."""
import json
import re
import shutil
import subprocess

import pytest

from tests.conftest import ROOT

WORKFLOW = json.loads((ROOT / "invoice-reconciliation-agent.json").read_text(encoding="utf-8"))
NODES = {n["name"]: n for n in WORKFLOW["nodes"]}
EXTRACT = "Extract Invoice Fields (Claude)"
PARSE = "Parse Invoice JSON"


def _next(name):
    return WORKFLOW["connections"][name]["main"][0][0]["node"]


def test_pipeline_order():
    order = ["Google Drive Trigger", "Parse PDF (Cloud Run)", EXTRACT, PARSE,
             "Lookup PO (Google Sheets)", "Compare Totals (Pure Python)",
             "Classify Discrepancy (Claude)", "Alert Bookkeeper (Slack)"]
    for a, b in zip(order, order[1:]):
        assert _next(a) == b


def test_no_node_reads_invoice_fields_from_raw_claude_response():
    # The Claude node returns the Messages API envelope; invoice fields only exist after parsing.
    text = json.dumps(WORKFLOW)
    assert not re.search(r'\$node\[\\"%s\\"\]\.json' % re.escape(EXTRACT), text)


@pytest.mark.parametrize("field", ["vendor_name", "invoice_number", "po_number"])
def test_slack_alert_reads_parsed_invoice_fields(field):
    assert f'$node["{PARSE}"].json.{field}' in NODES["Alert Bookkeeper (Slack)"]["parameters"]["text"]


def test_reconciler_and_po_lookup_use_parsed_invoice():
    assert f'$node["{PARSE}"].json' in NODES["Compare Totals (Pure Python)"]["parameters"]["jsonBody"]
    assert NODES["Lookup PO (Google Sheets)"]["parameters"]["lookupValue"] == "={{ $json.po_number || '' }}"


# ---------- Execute the Code node's JavaScript ----------

INVOICE = {"vendor_name": "Acme Office Supplies Inc.", "invoice_number": "INV-10088", "po_number": " po-8821 ",
           "line_items": [], "subtotal": 2500.0, "total_amount": 2500.0}


def run_parse_node(claude_response):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    js = NODES[PARSE]["parameters"]["jsCode"]
    harness = f"const $json = {json.dumps(claude_response)};\nconst out = (() => {{\n{js}\n}})();\nprocess.stdout.write(JSON.stringify(out));"
    proc = subprocess.run([node, "-e", harness], capture_output=True, text=True)
    return proc


def _ok(response):
    proc = run_parse_node(response)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["json"]


def test_parse_node_reads_text_after_thinking_block_and_normalizes_po():
    out = _ok({"content": [{"type": "thinking", "thinking": "", "signature": "s"},
                           {"type": "text", "text": json.dumps(INVOICE)}]})
    assert out["vendor_name"] == "Acme Office Supplies Inc."
    assert out["invoice_number"] == "INV-10088"
    assert out["po_number"] == "PO-8821"


def test_parse_node_handles_code_fenced_json():
    out = _ok({"content": [{"type": "text", "text": "Here it is:\n```json\n" + json.dumps(INVOICE) + "\n```"}]})
    assert out["invoice_number"] == "INV-10088"


def test_parse_node_keeps_missing_po_as_null():
    out = _ok({"content": [{"type": "text", "text": json.dumps({**INVOICE, "po_number": None})}]})
    assert out["po_number"] is None


@pytest.mark.parametrize("response, message", [
    ({"content": [{"type": "thinking", "thinking": ""}]}, "no text block"),
    ({"content": []}, "no text block"),
    ({"content": [{"type": "text", "text": "Sorry, I can't read this invoice."}]}, "did not contain a JSON object"),
])
def test_parse_node_fails_loudly_on_bad_responses(response, message):
    proc = run_parse_node(response)
    assert proc.returncode != 0
    assert message in proc.stderr
