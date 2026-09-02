from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import os
import tempfile
from services.parser import extract_invoice_text
from services.extractor import extract_invoice_fields
from services.reconciler import load_purchase_orders_from_csv, reconcile_invoice
from services.classifier import classify_discrepancy

app = FastAPI(title="Invoice Reconciliation Agent")

# Mount static files for the frontend
app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def read_root():
    with open("app/static/index.html", "r") as f:
        return f.read()

@app.post("/api/reconcile")
async def reconcile_document(file: UploadFile = File(...)):
    if not file.filename.endswith(('.txt', '.pdf')):
        raise HTTPException(status_code=400, detail="Only .txt and .pdf files are supported")

    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as temp_file:
        temp_file.write(await file.read())
        temp_path = temp_file.name

    try:
        invoice_text = extract_invoice_text(temp_path)
        
        if not os.getenv("ANTHROPIC_API_KEY"):
            raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY environment variable not set.")
        
        invoice_data = extract_invoice_fields(invoice_text)
        
        po_db = load_purchase_orders_from_csv("data/purchase_orders.csv")
        po_record = po_db.get(invoice_data.po_number)
        reconciliation_result = reconcile_invoice(invoice_data, po_record)
        
        classification = None
        if reconciliation_result.status != "MATCHED":
            classification = classify_discrepancy(reconciliation_result)
            
        return {
            "invoice_data": invoice_data.model_dump(),
            "reconciliation_result": reconciliation_result.model_dump(),
            "classification": classification.model_dump() if classification else None
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
