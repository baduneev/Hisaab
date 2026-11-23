import csv
import io
from datetime import date
from decimal import Decimal
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from . import models as m
from .schemas import ProductIn, ContactIn, DocumentIn
from .accounting import owned, tenant_lock, create_document, post_document, audit, ACCOUNTS, money

TEMPLATES = {
    "products": "name,sku,category,unit,pack_unit,pack_size,sale_price,reorder_level\nBasmati rice,RICE25,Food,bag,carton,4,1850,10\n",
    "contacts": "name,kind,pan,phone,email,address,credit_days\nExample customer,customer,,9800000000,,Kathmandu,30\n",
    "opening_stock": "date,sku,warehouse,quantity,unit_cost\n2026-11-01,RICE25,Main warehouse,10,1400\n",
    "opening_balances": "date,account,debit,credit,contact_id\n2026-11-01,1000,10000,0,\n2026-11-01,3000,0,10000,\n",
}


def parse_csv(text):
    try:
        reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
        if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise HTTPException(422, "CSV headers must be present and unique")
        rows = list(reader)
        if not rows or len(rows) > 5000:
            raise HTTPException(422, "Import between 1 and 5,000 rows at a time")
        if any(None in row or any(v is None for v in row.values()) for row in rows):
            raise HTTPException(422, "CSV row columns must match the header")
        return [{str(k).strip(): str(v).strip() for k, v in row.items()} for row in rows]
    except csv.Error:
        raise HTTPException(422, "The CSV could not be read")


def preview(db, user, data):
    rows = parse_csv(data.csv)
    normalized, errors, seen = [], [], set()
    for index, row in enumerate(rows, start=2):
        try:
            row = {k: v for k, v in row.items() if v != ""}
            if data.kind == "products":
                value = ProductIn.model_validate(row).model_dump(mode="json")
                if value["sku"] in seen or db.scalar(select(m.Product.id).where(m.Product.tenant_id == user.tenant_id, m.Product.sku == value["sku"])):
                    raise ValueError("SKU already exists in this company or file")
                seen.add(value["sku"])
            elif data.kind == "contacts":
                value = ContactIn.model_validate(row).model_dump(mode="json")
            elif data.kind == "opening_stock":
                product = db.scalar(select(m.Product).where(m.Product.tenant_id == user.tenant_id, m.Product.sku == row.get("sku")))
                warehouse = db.scalar(select(m.Warehouse).where(m.Warehouse.tenant_id == user.tenant_id, m.Warehouse.name == row.get("warehouse")))
                if not product or not warehouse:
                    raise ValueError("SKU or warehouse does not exist in this company")
                value = DocumentIn.model_validate({"kind": "opening_stock", "date": row["date"], "warehouse_id": warehouse.id, "lines": [{"product_id": product.id, "quantity": row["quantity"], "unit_price": row["unit_cost"]}]}).model_dump(mode="json")
            else:
                value = {"date": date.fromisoformat(row["date"]).isoformat(), "account": row["account"], "debit": str(money(row.get("debit", "0"))), "credit": str(money(row.get("credit", "0"))), "contact_id": row.get("contact_id")}
                if value["account"] not in ACCOUNTS or value["account"] == "1200":
                    raise ValueError("Invalid account; use opening stock for inventory")
                if value["contact_id"]:
                    owned(db, m.Contact, value["contact_id"], user.tenant_id)
                if not all(Decimal(value[k]).is_finite() and Decimal(value[k]) >= 0 for k in ["debit", "credit"]):
                    raise ValueError("Amounts must be finite and nonnegative")
            normalized.append(value)
        except (ValidationError, ValueError, KeyError, HTTPException, ArithmeticError) as exc:
            errors.append({"row": index, "message": str(exc.detail) if isinstance(exc, HTTPException) else str(exc)[:500]})
    if data.kind == "opening_balances" and not errors:
        if len({row["date"] for row in normalized}) > 1:
            errors.append({"row": 0, "message": "Opening entries must use one date"})
        if sum((Decimal(x["debit"]) - Decimal(x["credit"]) for x in normalized), Decimal(0)) != 0:
            errors.append({"row": 0, "message": "Opening debits must equal opening credits"})
    batch = m.ImportBatch(tenant_id=user.tenant_id, kind=data.kind, rows=normalized, errors=errors)
    db.add(batch)
    db.flush()
    audit(db, user, "import.previewed", batch.id, {"kind": data.kind, "rows": len(rows), "errors": len(errors)})
    return batch


def commit(db, user, batch_id, key):
    tenant_lock(db, user.tenant_id)
    batch = owned(db, m.ImportBatch, batch_id, user.tenant_id)
    if not key or not 8 <= len(key) <= 128:
        raise HTTPException(422, "An Idempotency-Key is required")
    prior = db.scalar(select(m.Idempotency).where(m.Idempotency.tenant_id == user.tenant_id, m.Idempotency.key == key))
    if prior and prior.operation != f"import:{batch.id}":
        raise HTTPException(409, "This idempotency key belongs to another operation")
    if batch.committed:
        return batch
    if batch.errors:
        raise HTTPException(422, "Fix the preview errors and upload the file again")
    if batch.kind in {"products", "contacts"}:
        schema, model = (ProductIn, m.Product) if batch.kind == "products" else (ContactIn, m.Contact)
        for row in batch.rows:
            db.add(model(tenant_id=user.tenant_id, **schema.model_validate(row).model_dump()))
    elif batch.kind == "opening_stock":
        for index, row in enumerate(batch.rows):
            doc = create_document(db, user, DocumentIn.model_validate(row))
            post_document(db, user, doc.id, f"import-{batch.id}-{index}")
    else:
        data = DocumentIn.model_validate({"kind": "opening_balance", "date": batch.rows[0]["date"], "entries": [{k: v for k, v in row.items() if k != "date"} for row in batch.rows]})
        doc = create_document(db, user, data)
        post_document(db, user, doc.id, f"import-{batch.id}-opening")
    batch.committed = True
    db.add(m.Idempotency(tenant_id=user.tenant_id, key=key, operation=f"import:{batch.id}", result_id=batch.id))
    audit(db, user, "import.committed", batch.id, {"rows": len(batch.rows)})
    db.flush()
    return batch
