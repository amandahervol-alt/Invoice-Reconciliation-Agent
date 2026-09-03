import os
import json
import re
from typing import List, Optional
from pydantic import BaseModel, Field
from anthropic import Anthropic, APIError, AuthenticationError
from dotenv import load_dotenv

load_dotenv()

class LineItem(BaseModel):
    description: str
    quantity: float
    unit_price: float
    total_price: float

class InvoiceData(BaseModel):
    vendor_name: str
    invoice_number: str
    po_number: Optional[str] = None
    invoice_date: Optional[str] = None
    line_items: List[LineItem] = []
    subtotal: float
    tax: float = 0.0
    shipping: float = 0.0
    total_amount: float
    raw_notes: Optional[str] = None

def extract_invoice_fields(raw_text: str) -> InvoiceData:
   """
    Calls Anthropic Claude to parse raw invoice text into structured InvoiceData.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key or api_key.strip() == "your_anthropic_api_key_here":
        raise ValueError("ANTHROPIC_API_KEY is missing or invalid in your .env file.")

     model_name = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
    client = Anthropic(api_key=api_key)

    system_prompt = (
        "You are an expert accounts payable invoice parsing assistant. "
        "Extract structured JSON from the invoice text below. "
        "Follow these rules strictly:\n"
        "1. Extract: vendor_name, invoice_number, po_number, invoice_date, line_items, subtotal, tax, shipping, total_amount.\n"
        "2. For each line item: description, quantity (float), unit_price (float), total_price (float).\n"
        "3. NEVER hallucinate numbers or items. If a value (like po_number) is not found, return null.\n"
        "4. Respond ONLY with a valid JSON object matching the schema."
    )

    user_prompt = f"Invoice Text:\n---\n{raw_text}\n---"

    try:
        response = client.messages.create(
            model=model_name,
            max_tokens=2048,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}]
        )
        raw_output = response.content[0].text.strip()
        
        # Regex extraction for JSON object
        match = re.search(r'(\{[\s\S]*\})', raw_output)
        if match:
            json_str = match.group(1)
        else:
            json_str = raw_output

        data = json.loads(json_str)
        return InvoiceData(**data)
    except AuthenticationError:
        raise ValueError("Anthropic Authentication failed: Your ANTHROPIC_API_KEY is invalid or expired.")
    except APIError as e:
        raise ValueError(f"Anthropic API error: {e.message}")
    except json.JSONDecodeError:
        raise ValueError(f"Failed to parse Claude JSON response: {raw_output}")
