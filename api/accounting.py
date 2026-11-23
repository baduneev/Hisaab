"""Transactional posting engine. All postings serialize on the tenant row in PostgreSQL."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from fastapi import HTTPException
from sqlalchemy import select, func
from . import models as m
from .calendar import fiscal_year, today, calendar_info
from .schemas import DocumentIn
from .security import allow_document, can_read_document, READ_COSTS

D = Decimal
ZERO = D("0")
CENT = D("0.01")
ACCOUNTS = {
    "1000": ("Cash in hand", "asset"), "1010": ("Bank account", "asset"),
    "1100": ("Accounts receivable", "asset"), "1200": ("Inventory", "asset"),
    "1300": ("Input VAT", "asset"), "2000": ("Accounts payable", "liability"),
    "2100": ("Goods received, not billed", "liability"), "2200": ("Output VAT", "liability"),
    "3000": ("Owner equity / opening balance", "equity"),
    "4000": ("Sales revenue", "income"), "5000": ("Cost of goods sold", "expense"),
    "6000": ("Operating expenses", "expense"), "6100": ("Rent and utilities", "expense"),
    "6200": ("Transport and delivery", "expense"), "6300": ("Stock adjustment expense", "expense"),
}
STOCK_KINDS = {"sale", "goods_receipt", "sale_return", "purchase_return", "opening_stock", "stock_adjustment", "transfer"}
PREFIX = {"sale": "INV", "quotation": "QUO", "purchase_order": "PO", "goods_receipt": "GR", "purchase_bill": "BILL", "sale_return": "CN", "purchase_return": "PR", "receipt": "REC", "payment": "PAY", "expense": "EXP", "journal": "JV", "opening_balance": "OB", "opening_stock": "OS", "stock_adjustment": "ADJ", "transfer": "TR"}


def money(value):
    return D(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def owned(db, model, record_id, tenant_id):
    record = db.scalar(select(model).where(model.id == record_id, model.tenant_id == tenant_id))
    if not record:
        raise HTTPException(404, "Record was not found in your company")
    return record


def tenant_lock(db, tenant_id):
    return db.scalar(select(m.Tenant).where(m.Tenant.id == tenant_id).with_for_update().execution_options(populate_existing=True))


def audit(db, user, action, record_id, details=None):
    db.add(m.Audit(tenant_id=user.tenant_id, user_id=user.id, action=action, record_id=record_id, details=details or {}))


def outstanding(db, doc, as_of=None):
    allocation_query = select(func.coalesce(func.sum(m.Allocation.amount), 0)).join(m.Document, m.Allocation.payment_id == m.Document.id).where(m.Allocation.tenant_id == doc.tenant_id, m.Allocation.document_id == doc.id)
    return_query = select(func.coalesce(func.sum(m.Document.total), 0)).where(m.Document.tenant_id == doc.tenant_id, m.Document.reference_id == doc.id, m.Document.status == "posted", m.Document.kind.in_(["sale_return", "purchase_return"]))
    if as_of:
        allocation_query = allocation_query.where(m.Document.date <= as_of, m.Allocation.allocated_on <= as_of)
        return_query = return_query.where(m.Document.date <= as_of)
    allocated = db.scalar(allocation_query) or ZERO
    returned = db.scalar(return_query) or ZERO
    if doc.kind == "purchase_bill" and doc.reference_id:
        query = select(func.coalesce(func.sum(m.Document.total), 0)).where(m.Document.tenant_id == doc.tenant_id, m.Document.reference_id == doc.reference_id, m.Document.status == "posted", m.Document.kind == "purchase_return")
        if as_of:
            query = query.where(m.Document.date <= as_of)
        returned += db.scalar(query) or ZERO
    if doc.payload.get("cash_sale"):
        return ZERO
    return max(ZERO, money(doc.total - allocated - returned))


def serialize_doc(db, doc, user):
    if not can_read_document(user, doc.kind):
        raise HTTPException(403, "This transaction is restricted to your accounting team")
    contact = owned(db, m.Contact, doc.contact_id, user.tenant_id) if doc.contact_id else None
    payload = dict(doc.payload)
    if user.role not in READ_COSTS:
        payload = {k: v for k, v in payload.items() if k not in {"entries", "cost_total"}}
        payload["lines"] = [{k: v for k, v in line.items() if k not in {"unit_cost", "cost", "inventory_cost"} and not (doc.kind in {"goods_receipt", "purchase_return", "stock_adjustment", "transfer"} and k in {"unit_price", "net", "tax", "total"})} for line in payload.get("lines", [])]
        if user.role == "Warehouse":
            payload.pop("net", None)
            payload.pop("tax", None)
            payload["amount"] = "0.00"
    financial = user.role != "Warehouse"
    return {"id": doc.id, "kind": doc.kind, "date": doc.date.isoformat(), "due_date": doc.due_date.isoformat() if doc.due_date else None,
            "contact_id": doc.contact_id, "contact_name": contact.name if contact else None,
            "warehouse_id": doc.warehouse_id, "reference_id": doc.reference_id, "number": doc.number,
            "status": doc.status, "total": str(money(doc.total)) if financial else "0.00",
            "outstanding": str(outstanding(db, doc)) if financial else "0.00", "payload": payload,
            "version": doc.version, "created_at": doc.created_at.isoformat(), "posted_at": doc.posted_at.isoformat() if doc.posted_at else None}


def validate_refs(db, user, data):
    if data.contact_id:
        c = owned(db, m.Contact, data.contact_id, user.tenant_id)
        customer_kinds = {"sale", "quotation", "sale_return", "receipt"}
        supplier_kinds = {"purchase_order", "goods_receipt", "purchase_bill", "purchase_return", "payment"}
        if (data.kind in customer_kinds and c.kind == "supplier") or (data.kind in supplier_kinds and c.kind == "customer"):
            raise HTTPException(422, "Select a contact of the correct type for this transaction")
    for warehouse_id in [data.warehouse_id, data.destination_id]:
        if warehouse_id:
            owned(db, m.Warehouse, warehouse_id, user.tenant_id)
    if data.reference_id:
        owned(db, m.Document, data.reference_id, user.tenant_id)
    for line in data.lines:
        owned(db, m.Product, line.product_id, user.tenant_id)
    for line in data.entries:
        if line.contact_id:
            owned(db, m.Contact, line.contact_id, user.tenant_id)
    for allocation in data.allocations:
        owned(db, m.Document, allocation.document_id, user.tenant_id)


def create_document(db, user, data: DocumentIn, tax_enabled=False):
    allow_document(user, data.kind)
    if (data.tax_invoice or any(line.tax_rate for line in data.lines)) and not tax_enabled:
        raise HTTPException(403, "Tax invoice issuance is disabled pending IRD verification. Save an internal transaction without VAT.")
    if data.tax_invoice or any(line.tax_rate for line in data.lines):
        tenant = db.get(m.Tenant, user.tenant_id)
        if not tenant.vat_registered or tenant.demo:
            raise HTTPException(403, "This company cannot issue VAT invoices")
    calendar_info(data.date.isoformat())
    validate_refs(db, user, data)
    contact = owned(db, m.Contact, data.contact_id, user.tenant_id) if data.contact_id else None
    doc = m.Document(tenant_id=user.tenant_id, kind=data.kind, date=data.date,
                     due_date=data.due_date or (data.date + timedelta(days=contact.credit_days) if contact and data.kind in {"sale", "purchase_bill"} else None),
                     contact_id=data.contact_id, warehouse_id=data.warehouse_id, reference_id=data.reference_id,
                     created_by=user.id, payload=data.model_dump(mode="json"))
    db.add(doc)
    db.flush()
    audit(db, user, "draft.created", doc.id, {"kind": data.kind})
    return doc


def change_stock(db, tenant_id, doc, product_id, warehouse_id, quantity, value):
    stock = db.scalar(select(m.Stock).where(m.Stock.tenant_id == tenant_id, m.Stock.product_id == product_id, m.Stock.warehouse_id == warehouse_id))
    if stock is None:
        stock = m.Stock(tenant_id=tenant_id, product_id=product_id, warehouse_id=warehouse_id, quantity=ZERO, value=ZERO)
        db.add(stock)
    new_quantity = stock.quantity + quantity
    new_value = money(stock.value + value)
    if new_quantity < 0 or new_value < 0:
        raise HTTPException(409, "Insufficient stock or stock value. Check the warehouse and quantity.")
    if not new_quantity and new_value:
        raise HTTPException(409, "Stock quantity and value would disagree")
    stock.quantity, stock.value = new_quantity, new_value
    db.add(m.StockMovement(tenant_id=tenant_id, document_id=doc.id, product_id=product_id, warehouse_id=warehouse_id, date=doc.date, quantity=quantity, value=money(value)))


def stock_cost(db, tenant_id, product_id, warehouse_id, quantity):
    stock = db.scalar(select(m.Stock).where(m.Stock.tenant_id == tenant_id, m.Stock.product_id == product_id, m.Stock.warehouse_id == warehouse_id))
    if stock is None or stock.quantity < quantity:
        raise HTTPException(409, "Insufficient stock. Receive stock before posting this transaction.")
    return stock.value if stock.quantity == quantity else money(stock.value / stock.quantity * quantity)


def allocate(db, user, payment, allocations):
    already = db.scalar(select(func.coalesce(func.sum(m.Allocation.amount), 0)).where(m.Allocation.tenant_id == user.tenant_id, m.Allocation.payment_id == payment.id)) or ZERO
    if sum((a.amount for a in allocations), ZERO) + already > payment.total:
        raise HTTPException(422, "Allocations exceed the available payment amount")
    for a in allocations:
        target = owned(db, m.Document, a.document_id, user.tenant_id)
        if target.status != "posted" or target.contact_id != payment.contact_id or target.kind != ("sale" if payment.kind == "receipt" else "purchase_bill"):
            raise HTTPException(422, "Allocate only to a posted invoice for the same contact")
        effective_date = payment.date if payment.status == "draft" else today()
        if target.date > effective_date:
            raise HTTPException(422, "An allocation cannot precede the invoice date")
        if a.amount > outstanding(db, target):
            raise HTTPException(422, "Allocation exceeds the invoice's remaining balance")
        db.add(m.Allocation(tenant_id=user.tenant_id, payment_id=payment.id, document_id=target.id, amount=money(a.amount), allocated_on=effective_date))
        db.flush()


def post_document(db, user, doc_id, key, tax_enabled=False):
    tenant = tenant_lock(db, user.tenant_id)
    doc = owned(db, m.Document, doc_id, tenant.id)
    allow_document(user, doc.kind)
    if not key or not 8 <= len(key) <= 128:
        raise HTTPException(422, "An Idempotency-Key of 8–128 characters is required")
    operation = f"post:{doc_id}"
    prior = db.scalar(select(m.Idempotency).where(m.Idempotency.tenant_id == tenant.id, m.Idempotency.key == key))
    if prior:
        if prior.operation != operation:
            raise HTTPException(409, "This idempotency key belongs to a different operation")
        return owned(db, m.Document, prior.result_id, tenant.id)
    if doc.status != "draft":
        raise HTTPException(409, "This transaction is already posted")
    if tenant.locked_through and doc.date <= tenant.locked_through:
        raise HTTPException(409, "This fiscal period is locked")
    if doc.date > today():
        raise HTTPException(422, "Future transactions cannot be posted")
    data = DocumentIn.model_validate(doc.payload)
    validate_refs(db, user, data)
    if (data.tax_invoice or any(x.tax_rate for x in data.lines)) and (not tax_enabled or not tenant.vat_registered or tenant.demo):
        raise HTTPException(403, "Tax billing is not enabled for this company")
    if doc.kind in STOCK_KINDS:
        if not doc.warehouse_id:
            raise HTTPException(422, "Choose a warehouse for stock transactions")
        if tenant.last_stock_date and doc.date < tenant.last_stock_date:
            raise HTTPException(409, "Backdated stock movements are not supported. Use the latest stock date or later.")
        tenant.last_stock_date = doc.date
    reference = owned(db, m.Document, doc.reference_id, tenant.id) if doc.reference_id else None
    if doc.kind in {"sale_return", "purchase_return", "purchase_bill"}:
        expected = {"sale_return": "sale", "purchase_return": "goods_receipt", "purchase_bill": "goods_receipt"}[doc.kind]
        if not reference or reference.kind != expected or reference.status != "posted" or reference.contact_id != doc.contact_id:
            raise HTTPException(422, f"Select the original posted {expected.replace('_', ' ')} for this contact")
        if doc.date < reference.date:
            raise HTTPException(422, "A correction cannot precede the original transaction")
        if doc.kind.endswith("return") and doc.warehouse_id != reference.warehouse_id:
            raise HTTPException(422, "Return goods to/from the original warehouse")
    if doc.kind == "purchase_bill":
        if db.scalar(select(m.Document.id).where(m.Document.tenant_id == tenant.id, m.Document.reference_id == reference.id, m.Document.kind == "purchase_bill", m.Document.status == "posted")):
            raise HTTPException(409, "This goods receipt has already been billed")
        # Reject billing after an unbilled return; the remaining quantity needs a new receipt.
        if db.scalar(select(m.Document.id).where(m.Document.tenant_id == tenant.id, m.Document.reference_id == reference.id, m.Document.kind == "purchase_return", m.Document.status == "posted")):
            raise HTTPException(409, "This receipt has returns. Resolve with your accountant before billing.")
    financial_lines = []

    def entry(account, debit=ZERO, credit=ZERO, contact_id=None):
        if money(debit) or money(credit):
            financial_lines.append({"account": account, "debit": money(debit), "credit": money(credit), "contact_id": contact_id})

    lines, net, tax, cost_total = [], ZERO, ZERO, ZERO
    if doc.kind in STOCK_KINDS | {"quotation", "purchase_order"}:
        if not data.lines:
            raise HTTPException(422, "Add at least one product")
        previous_returns = db.scalars(select(m.Document).where(m.Document.tenant_id == tenant.id, m.Document.reference_id == doc.reference_id, m.Document.kind == doc.kind, m.Document.status == "posted")).all() if doc.kind.endswith("return") else []
        for item in data.lines:
            product = owned(db, m.Product, item.product_id, tenant.id)
            qty = item.quantity * (product.pack_size if item.unit == "pack" else 1)
            unit_price, discount, rate = item.unit_price, item.discount, item.tax_rate
            original = None
            if doc.kind.endswith("return"):
                original = next((x for x in reference.payload["lines"] if x["product_id"] == item.product_id), None)
                if not original:
                    raise HTTPException(422, "This product is not in the original document")
                returned = sum((D(x["quantity"]) for d in previous_returns for x in d.payload["lines"] if x["product_id"] == item.product_id), ZERO)
                if qty + returned > D(original["quantity"]):
                    raise HTTPException(409, "Return quantity exceeds the quantity remaining from the original transaction")
                # Return net price and original stock cost, including any original line discount.
                line_net = money(D(original["net"]) * qty / D(original["quantity"]))
                line_tax = money(D(original["tax"]) * qty / D(original["quantity"]))
                if qty + returned == D(original["quantity"]):
                    old_net = sum((D(x["net"]) for d in previous_returns for x in d.payload["lines"] if x["product_id"] == item.product_id), ZERO)
                    old_tax = sum((D(x["tax"]) for d in previous_returns for x in d.payload["lines"] if x["product_id"] == item.product_id), ZERO)
                    line_net, line_tax = D(original["net"]) - old_net, D(original["tax"]) - old_tax
                unit_price = D(original["unit_price"])
            else:
                line_net = money(item.quantity * unit_price - discount)
                if line_net < 0:
                    raise HTTPException(422, "Discount cannot exceed the line value")
                line_tax = money(line_net * rate / 100)
            cost = ZERO
            if doc.kind in {"goods_receipt", "opening_stock"} or (doc.kind == "stock_adjustment" and data.adjustment == "increase"):
                cost = line_net
                if cost <= 0:
                    raise HTTPException(422, "Incoming stock must have a positive purchase cost")
                change_stock(db, tenant.id, doc, product.id, doc.warehouse_id, qty, cost)
            elif doc.kind in {"sale", "transfer"} or (doc.kind == "stock_adjustment" and data.adjustment == "decrease"):
                cost = stock_cost(db, tenant.id, product.id, doc.warehouse_id, qty)
                change_stock(db, tenant.id, doc, product.id, doc.warehouse_id, -qty, -cost)
                if doc.kind == "transfer":
                    if not data.destination_id or data.destination_id == doc.warehouse_id:
                        raise HTTPException(422, "Choose a different destination warehouse")
                    change_stock(db, tenant.id, doc, product.id, data.destination_id, qty, cost)
            elif doc.kind == "sale_return":
                cost = money(D(original["cost"]) * qty / D(original["quantity"]))
                if qty + returned == D(original["quantity"]):
                    cost = D(original["cost"]) - sum((D(x["cost"]) for d in previous_returns for x in d.payload["lines"] if x["product_id"] == item.product_id), ZERO)
                change_stock(db, tenant.id, doc, product.id, doc.warehouse_id, qty, cost)
            elif doc.kind == "purchase_return":
                # Return at the receipt's cost; recognize any difference from current average explicitly.
                cost = stock_cost(db, tenant.id, product.id, doc.warehouse_id, qty)
                change_stock(db, tenant.id, doc, product.id, doc.warehouse_id, -qty, -cost)
            lines.append({"product_id": product.id, "name": product.name, "sku": product.sku, "unit": product.unit, "quantity": str(qty), "unit_price": str(unit_price if item.unit == "base" else unit_price / product.pack_size), "discount": str(discount), "tax_rate": str(rate), "net": str(line_net), "tax": str(line_tax), "total": str(line_net + line_tax), "cost": str(cost)})
            net += line_net
            tax += line_tax
            cost_total += cost
            db.flush()
    total = money(net + tax)
    contact_id = doc.contact_id
    if doc.kind in {"sale", "quotation", "purchase_order", "goods_receipt", "purchase_bill", "sale_return", "purchase_return", "receipt", "payment"} and not contact_id:
        raise HTTPException(422, "Choose a customer or supplier")
    if doc.kind == "sale":
        entry(data.account if data.cash_sale else "1100", total, contact_id=contact_id if not data.cash_sale else None)
        entry("4000", credit=net)
        entry("2200", credit=tax)
        entry("5000", cost_total)
        entry("1200", credit=cost_total)
    elif doc.kind == "goods_receipt":
        if tax:
            raise HTTPException(422, "Record supplier VAT on the supplier bill, not the goods receipt")
        entry("1200", net)
        entry("2100", credit=net)
    elif doc.kind == "purchase_bill":
        net = reference.total
        # v1 supplier bills settle one full goods receipt; VAT is a separately reviewed capability.
        if data.lines or data.amount or data.tax_invoice:
            raise HTTPException(422, "Supplier bills inherit the full receipt value; do not add lines, amounts, or VAT")
        total, lines = net, reference.payload["lines"]
        entry("2100", net)
        entry("2000", credit=net, contact_id=contact_id)
    elif doc.kind == "sale_return":
        entry("4000", net)
        entry("2200", tax)
        entry(reference.payload.get("account", "1000") if reference.payload.get("cash_sale") else "1100", credit=total, contact_id=contact_id if not reference.payload.get("cash_sale") else None)
        entry("1200", cost_total)
        entry("5000", credit=cost_total)
    elif doc.kind == "purchase_return":
        bill = db.scalar(select(m.Document).where(m.Document.tenant_id == tenant.id, m.Document.reference_id == reference.id, m.Document.kind == "purchase_bill", m.Document.status == "posted"))
        entry("2000" if bill else "2100", total, contact_id=contact_id if bill else None)
        entry("1200", credit=cost_total)
        difference = cost_total - total
        entry("6300", max(difference, ZERO), max(-difference, ZERO))
    elif doc.kind == "opening_stock":
        entry("1200", net)
        entry("3000", credit=net)
    elif doc.kind == "stock_adjustment":
        if data.adjustment == "increase":
            entry("1200", cost_total)
            entry("6300", credit=cost_total)
        else:
            entry("6300", cost_total)
            entry("1200", credit=cost_total)
        total = cost_total
    elif doc.kind in {"receipt", "payment", "expense"}:
        total = money(data.amount)
        if total <= 0:
            raise HTTPException(422, "Enter a positive amount")
        if doc.kind == "receipt":
            entry(data.account, total)
            entry("1100", credit=total, contact_id=contact_id)
        elif doc.kind == "payment":
            entry("2000", total, contact_id=contact_id)
            entry(data.account, credit=total)
        else:
            entry(data.expense_account, total)
            entry(data.account, credit=total)
    elif doc.kind in {"journal", "opening_balance"}:
        if len(data.entries) < 2:
            raise HTTPException(422, "A journal needs at least two entries")
        for item in data.entries:
            if item.account not in ACCOUNTS or (item.debit and item.credit):
                raise HTTPException(422, "Choose a valid account and a debit or credit per line")
            if item.account == "1200":
                raise HTTPException(422, "Use stock documents to change inventory, preserving ledger reconciliation")
            if item.account in {"1100", "2000"} and not item.contact_id:
                raise HTTPException(422, "Receivable and payable entries need a contact")
            entry(item.account, item.debit, item.credit, item.contact_id)
        total = sum((x["debit"] for x in financial_lines), ZERO)
        if doc.kind == "journal" and reference:
            if reference.kind != "journal" or reference.status != "posted":
                raise HTTPException(422, "Only a posted manual journal can be reversed using a linked journal")
            old_journal = db.scalar(select(m.Journal).where(m.Journal.document_id == reference.id, m.Journal.tenant_id == tenant.id))
            old_lines = db.scalars(select(m.LedgerLine).where(m.LedgerLine.journal_id == old_journal.id, m.LedgerLine.tenant_id == tenant.id)).all()
            normalize = lambda rows: sorted((x["account"], str(money(x["debit"])), str(money(x["credit"])), x.get("contact_id") or "") for x in rows)
            reversed_lines = [{"account": x.account, "debit": x.credit, "credit": x.debit, "contact_id": x.contact_id} for x in old_lines]
            if normalize(financial_lines) != normalize(reversed_lines):
                raise HTTPException(422, "A reversal must exactly reverse the original journal")
            if db.scalar(select(m.Document.id).where(m.Document.tenant_id == tenant.id, m.Document.reference_id == reference.id, m.Document.status == "posted", m.Document.kind == "journal")):
                raise HTTPException(409, "This journal has already been reversed")
    if sum((x["debit"] for x in financial_lines), ZERO) != sum((x["credit"] for x in financial_lines), ZERO):
        raise HTTPException(422, "Journal debits must equal credits")
    if doc.kind not in {"quotation", "purchase_order", "transfer"} and not financial_lines:
        raise HTTPException(422, "This transaction has no financial value")
    fy = fiscal_year(doc.date)
    sequence_key = f"{fy}:{doc.kind}"
    seq = dict(tenant.sequences)
    seq[sequence_key] = seq.get(sequence_key, 0) + 1
    tenant.sequences = seq
    doc.number = f"{PREFIX[doc.kind]}-{fy}-{seq[sequence_key]:05d}"
    doc.total = total
    doc.payload = {**doc.payload, "lines": lines, "net": str(net), "tax": str(tax), "cost_total": str(cost_total)}
    if financial_lines:
        journal = m.Journal(tenant_id=tenant.id, document_id=doc.id, date=doc.date, description=f"{doc.number} {data.notes}"[:300])
        db.add(journal)
        db.flush()
        for line in financial_lines:
            db.add(m.LedgerLine(tenant_id=tenant.id, journal_id=journal.id, **line))
    # Flush all content while draft, then freeze it. Posted-document DB triggers reject later edits.
    db.flush()
    if doc.kind in {"receipt", "payment"}:
        allocate(db, user, doc, data.allocations)
    doc.status = "posted"
    doc.posted_at = m.now()
    doc.version += 1
    db.add(m.Idempotency(tenant_id=tenant.id, key=key, operation=operation, result_id=doc.id))
    audit(db, user, "transaction.posted", doc.id, {"number": doc.number, "total": str(total)})
    db.flush()
    return doc
