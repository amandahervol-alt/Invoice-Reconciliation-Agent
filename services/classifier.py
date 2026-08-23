import os
import json
import re
from typing import Dict, List, Optional
from pydantic import BaseModel
from anthropic import Anthropic, APIError, AuthenticationError
from dotenv import load_dotenv
from services.reconciler import ReconciliationResult

load_dotenv()

class DiscrepancyClassification(BaseModel):
    category: str
    severity: str  # "LOW", "MEDIUM", "HIGH", "CRITICAL", "NONE"
    explanation: str
    recommended_action: str
    slack_summary: str

def classify_discrepancy(result: ReconciliationResult) -> DiscrepancyClassification:
    """
    Uses Claude to analyze reconciliation mismatches and produce human-readable
    root causes and recommended bookkeeper actions.
    """
    if result.status == "MATCHED":
        return DiscrepancyClassification(
            category="PERFECT_MATCH",
            severity="NONE",
            explanation="All line items, quantities, unit prices, and totals match the approved Purchase Order.",
            recommended_action="Auto-approve for payment processing.",
            slack_summary=f"✅ Approved: Invoice #{result.invoice_number} matches PO #{result.po_number} (${result.invoice_total:.2f})"
        )

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key or api_key.strip() == "your_anthropic_api_key_here":
        # Graceful fallback if API key is not configured locally
        return DiscrepancyClassification(
            category="UNCLASSIFIED_DISCREPANCY",
            severity="HIGH" if not result.within_tolerance else "MEDIUM",
            explanation="; ".join(result.flags) if result.flags else result.summary,
            recommended_action="Manual AP review required before scheduling payment.",
            slack_summary=f"⚠️ Exception: Invoice #{result.invoice_number} vs PO #{result.po_number} (Variance: ${result.total_variance:+.2f})"
        )

    model_name = os.getenv("ANTHROPIC_MODEL", "claude-3-7-sonnet-20250219")
    client = Anthropic(api_key=api_key)

    system_prompt = (
        "You are an expert accounts payable discrepancy auditor. "
        "Analyze the provided mathematical reconciliation result and classify the issue.\n"
        "Categories to choose from: [PRICE_VARIANCE, QUANTITY_OVERAGE, UNAPPROVED_LINE_ITEM, MISSING_PO, VENDOR_MISMATCH, TAX_SHIPPING_VARIANCE].\n"
        "Severities: [LOW, MEDIUM, HIGH, CRITICAL].\n"
        "Provide:\n"
        "1. category\n"
        "2. severity\n"
        "3. explanation (1-2 clear sentences for the bookkeeper)\n"
        "4. recommended_action (actionable step for the finance team)\n"
        "5. slack_summary (a concise, emoji-formatted Slack alert message)\n"
        "Respond ONLY with a valid JSON object."
    )

    user_prompt = f"Reconciliation Data:\n{result.model_dump_json(indent=2)}"

    try:
        response = client.messages.create(
            model=model_name,
            max_tokens=1024,
            temperature=0.0,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}]
        )
        raw_output = response.content[0].text.strip()
        match = re.search(r'(\{[\s\S]*\})', raw_output)
        json_str = match.group(1) if match else raw_output
        data = json.loads(json_str)
        return DiscrepancyClassification(**data)
    except Exception as e:
        return DiscrepancyClassification(
            category="DISCREPANCY_FLAGGED",
            severity="HIGH",
            explanation=f"Variance detected: {'; '.join(result.flags)}",
            recommended_action="Review line items against original vendor agreement.",
            slack_summary=f"⚠️ Exception: Invoice #{result.invoice_number} variance ${result.total_variance:+.2f}"
        )
