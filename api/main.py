from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
import hashlib
import io
import csv
import json
import logging
import secrets
import time
from pathlib import Path
from typing import Annotated
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .config import settings
from . import models as m, schemas as s, accounting as a, reports, insights, imports
from .calendar import calendar_info, today
from .security import password_hash, verify_password, authenticated, new_session, require, FINANCE, READ_COSTS, can_read_document
from .pdf import invoice_pdf

logger = logging.getLogger("hisaab")


def create_app(database_url=None, testing=False):
    engine, factory = m.database(database_url or settings.database_url)

    @asynccontextmanager
    async def lifespan(app):
        if testing:
            m.Base.metadata.create_all(engine)
            from .db_guards import install_guards
            with engine.begin() as connection:
                install_guards(connection)
        if settings.tax_billing_enabled:
            raise RuntimeError("Live tax billing is not released. A verified IRD/CBMS adapter and compliance acceptance are required before enabling it.")
        if not testing and settings.demo_mode:
            from .seed import seed_demo
            with factory.begin() as db:
                seed_demo(db)
        yield
        engine.dispose()

    app = FastAPI(title="Hisaab Accounting API", version="0.1.0", lifespan=lifespan, description="Tenant-scoped accounting API. Posting requires an Idempotency-Key. Monetary values are decimal strings.")
    app.state.engine, app.state.session_factory = engine, factory
    app.state.testing, app.state.auth_attempts = testing, {}

    @app.middleware("http")
    async def guard_requests(request: Request, call_next):
        started, request_id = time.monotonic(), secrets.token_hex(8)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            allowed = {str(request.base_url).rstrip("/"), "http://127.0.0.1:5188", "http://localhost:5188"}
            if origin and origin not in allowed or request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "Cross-origin writes are not allowed"}, status_code=403)
            if int(request.headers.get("content-length", "0") or 0) > 2_500_000:
                return JSONResponse({"detail": "Request is too large"}, status_code=413)
        response = await call_next(request)
        response.headers.update({"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "same-origin", "X-Request-ID": request_id, "Cache-Control": "no-store" if request.url.path.startswith("/api") else "no-cache"})
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if response.status_code >= 400:
            logger.warning("request_failed method=%s path=%s status=%s request_id=%s elapsed_ms=%d", request.method, request.url.path, response.status_code, request_id, (time.monotonic()-started)*1000)
        return response

    @app.exception_handler(IntegrityError)
    async def integrity_error(request, exc):
        return JSONResponse({"detail": "A conflicting record already exists. Refresh and check for duplicates."}, status_code=409)

    def db_session(request: Request):
        with factory() as db:
            try:
                # A dashboard contains several queries; all must observe the same
                # committed posting snapshot while another user is doing business.
                if engine.dialect.name == "postgresql" and request.method == "GET":
                    db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    DB = Annotated[Session, Depends(db_session, scope="function")]

    def current_user(request: Request, db: DB):
        return authenticated(db, request.cookies.get("hisaab_session"))

    USER = Annotated[m.User, Depends(current_user)]

    def finance(user: USER):
        require(user, READ_COSTS)
        return user

    FIN = Annotated[m.User, Depends(finance)]

    def auth_limit(request, kind):
        if testing:
            return
        key = (request.client.host if request.client else "unknown", kind)
        window = int(time.time() // 900)
        attempts = app.state.auth_attempts
        if len(attempts) > 10000:
            app.state.auth_attempts = attempts = {k: v for k, v in attempts.items() if v[0] == window}
        previous_window, count = attempts.get(key, (window, 0))
        count = count if window == previous_window else 0
        if count >= (10 if kind == "register" else 30):
            raise HTTPException(429, "Too many attempts. Try again in 15 minutes.", headers={"Retry-After": "900"})
        attempts[key] = (window, count + 1)

    def session_cookie(response, token):
        response.set_cookie("hisaab_session", token, max_age=settings.session_hours * 3600, httponly=True, secure=settings.cookie_secure and not testing, samesite="strict", path="/")

    def user_info(db, user):
        company = db.get(m.Tenant, user.tenant_id)
        return {"id": user.id, "name": user.name, "email": user.email, "role": user.role, "tenant_id": user.tenant_id, "company": {"id": company.id, "name": company.name, "pan": company.pan, "address": company.address, "vat_registered": company.vat_registered, "locked_through": str(company.locked_through) if company.locked_through else None, "demo": company.demo}, "tax_billing_enabled": settings.tax_billing_enabled and company.vat_registered and not company.demo, "today": str(today()), "calendar": calendar_info(str(today()))}

    @app.get("/api/v1/health")
    def health(db: DB):
        db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "ready", "version": "0.1.0", "tax_billing_enabled": settings.tax_billing_enabled}

    @app.post("/api/v1/auth/register", status_code=201)
    def register(data: s.Register, request: Request, response: Response, db: DB):
        auth_limit(request, "register")
        tenant = m.Tenant(name=data.company)
        db.add(tenant)
        db.flush()
        user = m.User(tenant_id=tenant.id, name=data.name, email=data.email.lower(), password_hash=password_hash(data.password), role="Owner")
        db.add(user)
        db.flush()
        db.add(m.Warehouse(tenant_id=tenant.id, name="Main warehouse", branch="Main branch"))
        session_cookie(response, new_session(db, user, settings.session_hours))
        a.audit(db, user, "company.created", tenant.id)
        return user_info(db, user)

    @app.post("/api/v1/auth/login")
    def login(data: s.Login, request: Request, response: Response, db: DB):
        auth_limit(request, "login")
        user = db.scalar(select(m.User).where(m.User.email == data.email.lower(), m.User.active == True))
        valid = verify_password(data.password, user.password_hash) if user else verify_password(data.password, "scrypt$missing$" + "0" * 128)
        if not user or not valid:
            raise HTTPException(401, "Email or password is incorrect")
        session_cookie(response, new_session(db, user, settings.session_hours))
        return user_info(db, user)

    @app.post("/api/v1/auth/logout")
    def logout(request: Request, response: Response, db: DB):
        token = request.cookies.get("hisaab_session")
        if token:
            auth = db.get(m.AuthSession, hashlib.sha256(token.encode()).hexdigest())
            if auth:
                db.delete(auth)
        response.delete_cookie("hisaab_session", path="/")
        return {"signed_out": True}

    @app.get("/api/v1/me")
    def me(db: DB, user: USER):
        return user_info(db, user)

    @app.put("/api/v1/company")
    def company(data: s.CompanyIn, db: DB, user: USER):
        require(user, {"Owner"})
        tenant = a.tenant_lock(db, user.tenant_id)
        for k, v in data.model_dump().items():
            setattr(tenant, k, v)
        a.audit(db, user, "company.updated", tenant.id)
        return user_info(db, user)

    @app.get("/api/v1/users")
    def users(db: DB, user: USER):
        require(user, {"Owner"})
        return [{"id": x.id, "name": x.name, "email": x.email, "role": x.role, "active": x.active} for x in db.scalars(select(m.User).where(m.User.tenant_id == user.tenant_id))]

    @app.post("/api/v1/users", status_code=201)
    def add_user(data: s.UserIn, db: DB, user: USER):
        require(user, {"Owner"})
        new = m.User(tenant_id=user.tenant_id, name=data.name, email=data.email.lower(), password_hash=password_hash(data.password), role=data.role)
        db.add(new)
        db.flush()
        a.audit(db, user, "user.created", new.id, {"role": new.role})
        return {"id": new.id, "name": new.name, "email": new.email, "role": new.role}

    @app.get("/api/v1/contacts")
    def contacts(db: DB, user: USER):
        result = []
        for row in db.scalars(select(m.Contact).where(m.Contact.tenant_id == user.tenant_id).order_by(m.Contact.name)):
            if user.role == "Sales" and row.kind == "supplier":
                continue
            value = {"id": row.id, **{key: getattr(row, key) for key in s.ContactIn.model_fields}}
            if user.role != "Warehouse":
                value["balance"] = str(reports.contact_balance(db, user.tenant_id, row.id))
            result.append(value)
        return result

    @app.post("/api/v1/contacts", status_code=201)
    def add_contact(data: s.ContactIn, db: DB, user: USER):
        require(user, {"Owner", "Accountant", "Sales"})
        if user.role == "Sales" and data.kind != "customer":
            raise HTTPException(403, "Sales staff may create customer contacts only")
        row = m.Contact(tenant_id=user.tenant_id, **data.model_dump())
        db.add(row)
        db.flush()
        a.audit(db, user, "contact.created", row.id)
        return {"id": row.id, **data.model_dump(mode="json")}

    @app.get("/api/v1/contacts/{contact_id}/statement")
    def statement(contact_id: str, db: DB, user: USER):
        require(user, READ_COSTS | {"Sales"})
        contact = a.owned(db, m.Contact, contact_id, user.tenant_id)
        if user.role == "Sales" and contact.kind != "customer":
            raise HTTPException(403, "Supplier statements are restricted")
        docs = db.scalars(select(m.Document).where(m.Document.tenant_id == user.tenant_id, m.Document.contact_id == contact.id).order_by(m.Document.date.desc(), m.Document.created_at.desc())).all()
        unallocated, running, history = a.ZERO, a.ZERO, []
        for doc in docs:
            if doc.status == "posted" and doc.kind in {"receipt", "payment"}:
                allocated = db.scalar(select(func.coalesce(func.sum(m.Allocation.amount), 0)).where(m.Allocation.tenant_id == user.tenant_id, m.Allocation.payment_id == doc.id)) or a.ZERO
                unallocated += doc.total - allocated
        for line, journal in sorted(reports.ledger_rows(db, user.tenant_id), key=lambda x: (x[1].date, x[1].id)):
            if line.contact_id == contact.id:
                running += (line.credit - line.debit) if line.account == "2000" else (line.debit - line.credit)
                history.append({"date": str(journal.date), "description": journal.description, "debit": str(line.debit), "credit": str(line.credit), "balance": str(a.money(running)), "document_id": journal.document_id})
        return {"contact": {"id": contact.id, **{key: getattr(contact, key) for key in s.ContactIn.model_fields}}, "balance": str(reports.contact_balance(db, user.tenant_id, contact.id)), "unallocated": str(a.money(unallocated)), "documents": [a.serialize_doc(db, x, user) for x in docs if can_read_document(user, x.kind)], "ledger": history, "aging": [x for x in reports.aging(db, user.tenant_id, "purchase_bill" if contact.kind == "supplier" else "sale") if x["contact_id"] == contact.id]}

    @app.get("/api/v1/products")
    def products(db: DB, user: USER):
        return [{"id": x.id, **{key: str(getattr(x, key)) if isinstance(getattr(x, key), Decimal) else getattr(x, key) for key in s.ProductIn.model_fields}} for x in db.scalars(select(m.Product).where(m.Product.tenant_id == user.tenant_id).order_by(m.Product.name))]

    @app.post("/api/v1/products", status_code=201)
    def add_product(data: s.ProductIn, db: DB, user: USER):
        require(user, FINANCE | {"Warehouse"})
        row = m.Product(tenant_id=user.tenant_id, **data.model_dump())
        db.add(row)
        db.flush()
        a.audit(db, user, "product.created", row.id)
        return {"id": row.id, **data.model_dump(mode="json")}

    @app.get("/api/v1/warehouses")
    def warehouses(db: DB, user: USER):
        return [{"id": x.id, "name": x.name, "branch": x.branch} for x in db.scalars(select(m.Warehouse).where(m.Warehouse.tenant_id == user.tenant_id).order_by(m.Warehouse.name))]

    @app.post("/api/v1/warehouses", status_code=201)
    def add_warehouse(data: s.WarehouseIn, db: DB, user: USER):
        require(user, FINANCE)
        row = m.Warehouse(tenant_id=user.tenant_id, **data.model_dump())
        db.add(row)
        db.flush()
        a.audit(db, user, "warehouse.created", row.id)
        return {"id": row.id, **data.model_dump()}

    @app.get("/api/v1/stock")
    def stock(db: DB, user: USER):
        rows = db.execute(select(m.Stock, m.Product, m.Warehouse).join(m.Product, m.Stock.product_id == m.Product.id).join(m.Warehouse, m.Stock.warehouse_id == m.Warehouse.id).where(m.Stock.tenant_id == user.tenant_id, m.Product.tenant_id == user.tenant_id, m.Warehouse.tenant_id == user.tenant_id)).all()
        result = []
        for st, product, warehouse in rows:
            value = {"id": st.id, "product_id": product.id, "name": product.name, "sku": product.sku, "category": product.category, "unit": product.unit, "warehouse_id": warehouse.id, "warehouse": warehouse.name, "branch": warehouse.branch, "quantity": str(st.quantity), "reorder_level": str(product.reorder_level), "low_stock": st.quantity <= product.reorder_level and product.reorder_level > 0, "sale_price": str(product.sale_price)}
            if user.role in READ_COSTS:
                value.update({"value": str(a.money(st.value)), "average_cost": str((st.value / st.quantity).quantize(Decimal("0.000001"))) if st.quantity else "0"})
            result.append(value)
        return result

    @app.get("/api/v1/stock/movements")
    def stock_movements(db: DB, user: USER, product_id: str | None = None):
        query = select(m.StockMovement).where(m.StockMovement.tenant_id == user.tenant_id)
        if product_id:
            a.owned(db, m.Product, product_id, user.tenant_id)
            query = query.where(m.StockMovement.product_id == product_id)
        return [{"id": x.id, "document_id": x.document_id, "product_id": x.product_id, "warehouse_id": x.warehouse_id, "date": str(x.date), "quantity": str(x.quantity), **({"value": str(x.value)} if user.role in READ_COSTS else {})} for x in db.scalars(query.order_by(m.StockMovement.date.desc()).limit(1000))]

    @app.get("/api/v1/documents", response_model=list[s.DocumentOut])
    def documents(db: DB, user: USER, kind: str | None = None, contact_id: str | None = None, limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0)):
        query = select(m.Document).where(m.Document.tenant_id == user.tenant_id)
        if kind:
            query = query.where(m.Document.kind.in_(kind.split(",")))
        if contact_id:
            a.owned(db, m.Contact, contact_id, user.tenant_id)
            query = query.where(m.Document.contact_id == contact_id)
        return [a.serialize_doc(db, doc, user) for doc in db.scalars(query.order_by(m.Document.date.desc(), m.Document.created_at.desc()).offset(offset).limit(limit)) if can_read_document(user, doc.kind)]

    @app.post("/api/v1/documents", status_code=201, response_model=s.DocumentOut)
    def add_document(data: s.DocumentIn, db: DB, user: USER):
        return a.serialize_doc(db, a.create_document(db, user, data, settings.tax_billing_enabled), user)

    @app.get("/api/v1/documents/{doc_id}", response_model=s.DocumentOut)
    def document(doc_id: str, db: DB, user: USER):
        return a.serialize_doc(db, a.owned(db, m.Document, doc_id, user.tenant_id), user)

    @app.patch("/api/v1/documents/{doc_id}", response_model=s.DocumentOut)
    def edit_document(doc_id: str, data: dict, db: DB, user: USER, if_match: str = Header(default="")):
        a.tenant_lock(db, user.tenant_id)
        doc = a.owned(db, m.Document, doc_id, user.tenant_id)
        a.allow_document(user, doc.kind)
        if doc.status != "draft":
            raise HTTPException(409, "Posted records cannot be edited. Create a linked correction.")
        if if_match != str(doc.version):
            raise HTTPException(412, "This draft changed. Reload before saving.")
        if "kind" in data and data["kind"] != doc.kind:
            raise HTTPException(422, "A draft's transaction type cannot change")
        try:
            value = s.DocumentIn.model_validate({**doc.payload, **data})
        except Exception as exc:
            raise HTTPException(422, "Draft changes are invalid") from exc
        a.validate_refs(db, user, value)
        if value.tax_invoice or any(x.tax_rate for x in value.lines):
            raise HTTPException(403, "Tax draft editing is disabled pending verification")
        for key in ["date", "due_date", "contact_id", "warehouse_id", "reference_id"]:
            setattr(doc, key, getattr(value, key))
        doc.payload = value.model_dump(mode="json")
        doc.version += 1
        a.audit(db, user, "draft.updated", doc.id)
        return a.serialize_doc(db, doc, user)

    @app.post("/api/v1/documents/{doc_id}/post", response_model=s.DocumentOut)
    def post_document(doc_id: str, db: DB, user: USER, idempotency_key: str = Header(default="")):
        return a.serialize_doc(db, a.post_document(db, user, doc_id, idempotency_key, settings.tax_billing_enabled), user)

    @app.post("/api/v1/payments/{doc_id}/allocate")
    def allocate_payment(doc_id: str, data: s.AllocateIn, db: DB, user: USER):
        require(user, FINANCE | {"Sales"})
        a.tenant_lock(db, user.tenant_id)
        payment = a.owned(db, m.Document, doc_id, user.tenant_id)
        a.allow_document(user, payment.kind)
        if payment.kind not in {"receipt", "payment"} or payment.status != "posted":
            raise HTTPException(422, "Select a posted payment or receipt")
        a.allocate(db, user, payment, data.allocations)
        a.audit(db, user, "payment.allocated", payment.id)
        return {"allocated": True}

    @app.get("/api/v1/documents/{doc_id}/pdf")
    def pdf(doc_id: str, db: DB, user: USER):
        doc = a.owned(db, m.Document, doc_id, user.tenant_id)
        a.serialize_doc(db, doc, user)
        if user.role == "Warehouse":
            raise HTTPException(403, "Financial PDFs are restricted")
        company = db.get(m.Tenant, user.tenant_id)
        contact = a.owned(db, m.Contact, doc.contact_id, user.tenant_id) if doc.contact_id else None
        filename = (doc.number or doc.id).replace("/", "-") + ".pdf"
        return Response(invoice_pdf(company, doc, contact), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    @app.get("/api/v1/accounts")
    def accounts(db: DB, user: FIN):
        return [{"code": code, "name": value[0], "type": value[1]} for code, value in a.ACCOUNTS.items()]

    @app.get("/api/v1/journals")
    def journals(db: DB, user: FIN):
        result = []
        for journal in db.scalars(select(m.Journal).where(m.Journal.tenant_id == user.tenant_id).order_by(m.Journal.date.desc()).limit(1000)):
            lines = db.scalars(select(m.LedgerLine).where(m.LedgerLine.tenant_id == user.tenant_id, m.LedgerLine.journal_id == journal.id)).all()
            result.append({"id": journal.id, "document_id": journal.document_id, "date": str(journal.date), "description": journal.description, "entries": [{"account": x.account, "name": a.ACCOUNTS[x.account][0], "debit": str(x.debit), "credit": str(x.credit), "contact_id": x.contact_id} for x in lines]})
        return result

    def dates(start, end):
        if start and end and start > end:
            raise HTTPException(422, "Start date must not follow end date")

    @app.get("/api/v1/reports/summary")
    def summary(db: DB, user: FIN, start: date | None = None, end: date | None = None):
        dates(start, end)
        return reports.summary(db, user.tenant_id, start, end)

    @app.get("/api/v1/reports/trial-balance")
    def trial(db: DB, user: FIN, start: date | None = None, end: date | None = None):
        dates(start, end)
        return reports.trial_balance(db, user.tenant_id, end, start)

    @app.get("/api/v1/reports/financial-statements")
    def statements(db: DB, user: FIN, start: date | None = None, end: date | None = None):
        dates(start, end)
        return reports.financial_statements(db, user.tenant_id, start, end)

    @app.get("/api/v1/reports/aging")
    def report_aging(db: DB, user: USER, kind: str = "sale", end: date | None = None):
        require(user, READ_COSTS | ({"Sales"} if kind == "sale" else set()))
        if kind not in {"sale", "purchase_bill"}:
            raise HTTPException(422, "Choose sale or purchase_bill")
        return reports.aging(db, user.tenant_id, kind, end)

    @app.get("/api/v1/reports/margins")
    def margins(db: DB, user: FIN, start: date | None = None, end: date | None = None):
        dates(start, end)
        return reports.product_margins(db, user.tenant_id, start, end)

    @app.get("/api/v1/reports/inventory")
    def valuation(db: DB, user: FIN, end: date | None = None):
        return reports.inventory_valuation(db, user.tenant_id, end)

    @app.get("/api/v1/reports/export")
    def export(db: DB, user: FIN, kind: str = "trial-balance", start: date | None = None, end: date | None = None):
        dates(start, end)
        if kind == "trial-balance":
            values = reports.trial_balance(db, user.tenant_id, end)
        elif kind in {"receivables", "payables"}:
            values = reports.aging(db, user.tenant_id, "purchase_bill" if kind == "payables" else "sale", end)
        elif kind == "inventory":
            values = reports.inventory_valuation(db, user.tenant_id, end)
        elif kind == "margins":
            values = reports.product_margins(db, user.tenant_id, start, end)
        elif kind in {"profit", "balance", "cashflow"}:
            data = reports.financial_statements(db, user.tenant_id, start, end)
            if kind == "profit":
                values = [{"group": group, **row} for group in ["income", "expenses"] for row in data["profit_loss"][group]] + [{"group": "result", "account": "", "name": "Net profit", "amount": data["profit_loss"]["net_profit"]}]
            elif kind == "balance":
                values = [{"group": group, **row} for group in ["assets", "liabilities", "equity"] for row in data["balance_sheet"][group]] + [{"group": "equity", "account": "", "name": "Accumulated earnings", "amount": data["balance_sheet"]["retained_earnings"]}]
            else:
                values = [{"name": name, "amount": amount} for name, amount in data["cash_flow"].items()]
        else:
            raise HTTPException(422, "Unknown report export")
        content = io.StringIO()
        if values:
            writer = csv.DictWriter(content, fieldnames=values[0].keys())
            writer.writeheader()
            for value in values:
                writer.writerow({k: ("'" + str(v)) if str(v).startswith(("=", "+", "-", "@", "\t", "\r")) else v for k, v in value.items()})
        return Response(content.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{kind}.csv"'})

    @app.get("/api/v1/calendar")
    def calendar(db: DB, user: USER, date: str = "", calendar: str = "ad"):
        return calendar_info(date or str(today()), calendar)

    @app.post("/api/v1/periods/lock")
    def lock_period(data: s.LockIn, db: DB, user: USER):
        require(user, FINANCE)
        tenant = a.tenant_lock(db, user.tenant_id)
        if data.through > today() or (tenant.locked_through and data.through < tenant.locked_through):
            raise HTTPException(422, "Period locks can only advance through today")
        tenant.locked_through = data.through
        a.audit(db, user, "period.locked", tenant.id, {"through": str(data.through)})
        return {"locked_through": str(data.through)}

    @app.get("/api/v1/imports/templates/{kind}")
    def import_template(kind: str, db: DB, user: USER):
        require(user, FINANCE)
        if kind not in imports.TEMPLATES:
            raise HTTPException(404, "Unknown template")
        return Response(imports.TEMPLATES[kind], media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{kind}-template.csv"'})

    @app.post("/api/v1/imports/preview")
    def import_preview(data: s.ImportIn, db: DB, user: USER):
        require(user, FINANCE)
        batch = imports.preview(db, user, data)
        return {"id": batch.id, "valid": not batch.errors, "rows": batch.rows[:100], "row_count": len(batch.rows), "errors": batch.errors}

    @app.post("/api/v1/imports/{batch_id}/commit")
    def import_commit(batch_id: str, db: DB, user: USER, idempotency_key: str = Header(default="")):
        require(user, FINANCE)
        batch = imports.commit(db, user, batch_id, idempotency_key)
        return {"id": batch.id, "committed": batch.committed, "rows": len(batch.rows)}

    @app.get("/api/v1/bank-statements")
    def bank_rows(db: DB, user: FIN):
        return [{"id": x.id, "account": x.account, "date": str(x.date), "description": x.description, "amount": str(x.amount), "document_id": x.document_id} for x in db.scalars(select(m.BankRow).where(m.BankRow.tenant_id == user.tenant_id).order_by(m.BankRow.date.desc()))]

    @app.post("/api/v1/bank-statements", status_code=201)
    def bank_import(data: s.BankImport, db: DB, user: USER):
        require(user, FINANCE)
        a.tenant_lock(db, user.tenant_id)
        result = []
        for index, row in enumerate(imports.parse_csv(data.csv)):
            try:
                day, amount, description = date.fromisoformat(row["date"]), a.money(row["amount"]), row["description"][:300]
                if not amount.is_finite() or amount == 0 or abs(amount) > 99999999999:
                    raise ValueError("Invalid amount")
            except (KeyError, ValueError, ArithmeticError):
                raise HTTPException(422, f"Invalid bank statement row {index + 2}; use date,description,amount headers")
            fingerprint = hashlib.sha256(json.dumps([str(day), str(amount), description, data.account, row.get("reference", "")]).encode()).hexdigest()
            record = m.BankRow(tenant_id=user.tenant_id, account=data.account, date=day, description=description, amount=amount, fingerprint=fingerprint)
            db.add(record)
            db.flush()
            result.append({"id": record.id, "date": str(day), "description": description, "amount": str(amount)})
        a.audit(db, user, "bank.imported", user.tenant_id, {"rows": len(result)})
        return result

    @app.post("/api/v1/bank-statements/{row_id}/match")
    def bank_match(row_id: str, data: s.MatchIn, db: DB, user: USER):
        require(user, FINANCE)
        a.tenant_lock(db, user.tenant_id)
        row = a.owned(db, m.BankRow, row_id, user.tenant_id)
        doc = a.owned(db, m.Document, data.document_id, user.tenant_id)
        if row.document_id:
            raise HTTPException(409, "This statement transaction is already matched")
        if doc.status != "posted" or doc.date != row.date:
            raise HTTPException(422, "Match a posted transaction on the same date")
        journal = db.scalar(select(m.Journal).where(m.Journal.tenant_id == user.tenant_id, m.Journal.document_id == doc.id))
        amount = sum((x.debit - x.credit for x in db.scalars(select(m.LedgerLine).where(m.LedgerLine.tenant_id == user.tenant_id, m.LedgerLine.journal_id == (journal.id if journal else ""), m.LedgerLine.account == row.account))), a.ZERO)
        if amount != row.amount:
            raise HTTPException(422, "The account and exact signed amount must match")
        row.document_id = doc.id
        a.audit(db, user, "bank.matched", row.id, {"document_id": doc.id})
        return {"matched": True}

    @app.get("/api/v1/insights")
    def insight_snapshot(db: DB, user: FIN):
        return insights.snapshot(db, user.tenant_id)

    @app.post("/api/v1/insights/ask")
    def ask(data: s.AskIn, db: DB, user: FIN):
        a.tenant_lock(db, user.tenant_id)
        usage = db.scalar(select(m.AIUsage).where(m.AIUsage.tenant_id == user.tenant_id, m.AIUsage.date == today()))
        if usage is None:
            usage = m.AIUsage(tenant_id=user.tenant_id, date=today(), requests=0)
            db.add(usage)
        if usage.requests >= settings.ai_daily_limit:
            raise HTTPException(429, "Your daily explanation limit is reached. Numeric insights remain available.")
        usage.requests += 1
        evidence = insights.snapshot(db, user.tenant_id)
        result = insights.answer(data.question, data.language, evidence)
        db.commit()
        explanation = insights.provider_explanation(settings, data.question, data.language, evidence)
        if explanation:
            result["suggestion"], result["provider_status"] = explanation, "ai_assisted"
        elif settings.ai_api_key:
            result["provider_status"] = "fallback"
        return result

    @app.get("/api/v1/audit")
    def audit_log(db: DB, user: FIN):
        return [{"id": x.id, "action": x.action, "record_id": x.record_id, "details": x.details, "created_at": x.created_at.isoformat()} for x in db.scalars(select(m.Audit).where(m.Audit.tenant_id == user.tenant_id).order_by(m.Audit.created_at.desc()).limit(500))]

    @app.post("/api/v1/jobs", status_code=201)
    def create_job(data: dict, db: DB, user: FIN):
        kind = data.get("kind")
        if kind not in {"insights", "pdf", "import"}:
            raise HTTPException(422, "Choose insights, pdf, or import")
        if kind == "pdf":
            a.owned(db, m.Document, data.get("document_id"), user.tenant_id)
        if kind == "import":
            require(user, FINANCE)
            a.owned(db, m.ImportBatch, data.get("batch_id"), user.tenant_id)
        job = m.Job(tenant_id=user.tenant_id, created_by=user.id, kind=kind, payload={k: data[k] for k in ["document_id", "batch_id"] if k in data})
        db.add(job)
        db.flush()
        return {"id": job.id, "status": job.status}

    @app.get("/api/v1/jobs/{job_id}")
    def job_status(job_id: str, db: DB, user: FIN):
        job = a.owned(db, m.Job, job_id, user.tenant_id)
        return {"id": job.id, "kind": job.kind, "status": job.status, "result": job.result, "attempts": job.attempts}

    dist = Path(__file__).parent.parent / "dist"
    if dist.exists():
        from starlette.exceptions import HTTPException as StarletteHTTPException
        class SPAFiles(StaticFiles):
            async def get_response(self, path, scope):
                if path.startswith("api/") or path.startswith("openapi"):
                    raise StarletteHTTPException(404)
                try:
                    return await super().get_response(path, scope)
                except StarletteHTTPException as error:
                    if error.status_code == 404 and "." not in path.rsplit("/", 1)[-1]:
                        return await super().get_response("index.html", scope)
                    raise
        app.mount("/", SPAFiles(directory=str(dist), html=True), name="web")
    return app


app = create_app()
