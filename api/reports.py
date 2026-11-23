from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from sqlalchemy import select
from . import models as m
from .accounting import ACCOUNTS, ZERO, money, outstanding
from .calendar import today


def ledger_rows(db, tenant_id, end=None, start=None):
    query = select(m.LedgerLine, m.Journal).join(m.Journal, m.LedgerLine.journal_id == m.Journal.id).where(m.LedgerLine.tenant_id == tenant_id, m.Journal.tenant_id == tenant_id)
    if end:
        query = query.where(m.Journal.date <= end)
    if start:
        query = query.where(m.Journal.date >= start)
    return db.execute(query).all()


def balances(db, tenant_id, end=None, start=None):
    values = defaultdict(lambda: ZERO)
    for line, journal in ledger_rows(db, tenant_id, end, start):
        values[line.account] += line.debit - line.credit
    return values


def trial_balance(db, tenant_id, end=None, start=None):
    values = balances(db, tenant_id, end, start)
    return [{"account": code, "name": name, "type": kind, "debit": str(money(max(values[code], ZERO))), "credit": str(money(max(-values[code], ZERO)))} for code, (name, kind) in ACCOUNTS.items()]


def contact_balance(db, tenant_id, contact_id, end=None):
    value = ZERO
    for line, journal in ledger_rows(db, tenant_id, end):
        if line.contact_id == contact_id and line.account in {"1100", "2000"}:
            value += (line.credit - line.debit) if line.account == "2000" else (line.debit - line.credit)
    return money(value)


def aging(db, tenant_id, kind="sale", end=None):
    end = end or today()
    docs = db.scalars(select(m.Document).where(m.Document.tenant_id == tenant_id, m.Document.kind == kind, m.Document.status == "posted", m.Document.date <= end).order_by(m.Document.due_date)).all()
    result = []
    for doc in docs:
        remaining = outstanding(db, doc, end)
        if remaining <= 0:
            continue
        contact = db.get(m.Contact, doc.contact_id)
        overdue = max(0, (end - (doc.due_date or doc.date)).days)
        bucket = "current" if not overdue else "1–30" if overdue <= 30 else "31–60" if overdue <= 60 else "61–90" if overdue <= 90 else "90+"
        result.append({"id": doc.id, "number": doc.number, "contact_id": doc.contact_id, "contact_name": contact.name, "date": str(doc.date), "due_date": str(doc.due_date or doc.date), "amount": str(remaining), "days_overdue": overdue, "bucket": bucket, "href": f"/documents/{doc.id}"})
    return result


def summary(db, tenant_id, start=None, end=None):
    end = end or today()
    start = start or end.replace(day=1)
    all_bal = balances(db, tenant_id, end)
    period_bal = balances(db, tenant_id, end, start)
    # Historical inventory comes from immutable movements, rather than today's stock snapshot.
    movement_query = select(m.StockMovement).where(m.StockMovement.tenant_id == tenant_id, m.StockMovement.date <= end)
    inventory = sum((x.value for x in db.scalars(movement_query)), ZERO)
    receivables, payables = aging(db, tenant_id, "sale", end), aging(db, tenant_id, "purchase_bill", end)
    sales = -period_bal["4000"]
    cogs = period_bal["5000"]
    expense = sum((period_bal[code] for code in ["6000", "6100", "6200", "6300"]), ZERO)
    history = defaultdict(lambda: {"sales": ZERO, "cost": ZERO, "cash_in": ZERO, "cash_out": ZERO})
    for line, journal in ledger_rows(db, tenant_id, end, start):
        key = str(journal.date)
        if line.account == "4000":
            history[key]["sales"] += line.credit - line.debit
        if line.account == "5000":
            history[key]["cost"] += line.debit - line.credit
        if line.account in {"1000", "1010"}:
            history[key]["cash_in"] += line.debit
            history[key]["cash_out"] += line.credit
    products = db.scalars(select(m.Product).where(m.Product.tenant_id == tenant_id)).all()
    stocks = db.scalars(select(m.Stock).where(m.Stock.tenant_id == tenant_id)).all()
    product_stock = defaultdict(lambda: ZERO)
    for stock in stocks:
        product_stock[stock.product_id] += stock.quantity
    stock_alerts = [{"id": p.id, "name": p.name, "sku": p.sku, "quantity": str(product_stock[p.id]), "reorder_level": str(p.reorder_level), "unit": p.unit, "href": f"/inventory?product={p.id}"} for p in products if p.reorder_level > 0 and product_stock[p.id] <= p.reorder_level]
    last_post = db.scalar(select(m.Document.posted_at).where(m.Document.tenant_id == tenant_id, m.Document.status == "posted").order_by(m.Document.posted_at.desc()).limit(1))
    return {"period": {"start": str(start), "end": str(end)}, "as_of": m.now().isoformat(), "last_posted_at": last_post.isoformat() if last_post else None,
            "cash": str(money(all_bal["1000"] + all_bal["1010"])), "cash_in_hand": str(money(all_bal["1000"])), "bank": str(money(all_bal["1010"])),
            "sales": str(money(sales)), "cost_of_goods_sold": str(money(cogs)), "gross_profit": str(money(sales - cogs)), "expenses": str(money(expense)), "net_profit": str(money(sales - cogs - expense)),
            "receivables": str(money(all_bal["1100"])), "payables": str(money(-all_bal["2000"])), "inventory_value": str(money(inventory)),
            "overdue": str(money(sum((Decimal(x["amount"]) for x in receivables if x["days_overdue"] > 0), ZERO))),
            "upcoming_dues": str(money(sum((Decimal(x["amount"]) for x in payables if x["due_date"] <= str(end + timedelta(days=7))), ZERO))),
            "collections": receivables, "supplier_dues": payables, "stock_alerts": stock_alerts,
            "history": [{"date": key, **{k: str(money(v)) for k, v in value.items()}} for key, value in sorted(history.items())],
            "checks": {"journal_balanced": sum(all_bal.values(), ZERO) == ZERO, "inventory_reconciled": money(inventory) == money(all_bal["1200"])}}


def financial_statements(db, tenant_id, start=None, end=None):
    end = end or today()
    start = start or end.replace(day=1)
    values = balances(db, tenant_id, end)
    period = balances(db, tenant_id, end, start)
    rows = lambda kind, source: [{"account": code, "name": name, "amount": str(money(source[code] if kind in {"asset", "expense"} else -source[code]))} for code, (name, group) in ACCOUNTS.items() if group == kind]
    assets = sum((values[code] for code, (_, kind) in ACCOUNTS.items() if kind == "asset"), ZERO)
    liabilities = -sum((values[code] for code, (_, kind) in ACCOUNTS.items() if kind == "liability"), ZERO)
    equity = -values["3000"]
    retained = -sum((values[code] for code, (_, kind) in ACCOUNTS.items() if kind in {"income", "expense"}), ZERO)
    cashflow = defaultdict(lambda: ZERO)
    for line, journal in ledger_rows(db, tenant_id, end, start):
        if line.account in {"1000", "1010"}:
            cashflow["inflows"] += line.debit
            cashflow["outflows"] += line.credit
    opening_cash = balances(db, tenant_id, start - timedelta(days=1))
    return {"period": {"start": str(start), "end": str(end)},
            "profit_loss": {"income": rows("income", period), "expenses": rows("expense", period), "net_profit": str(money(-sum((period[code] for code, (_, kind) in ACCOUNTS.items() if kind in {"income", "expense"}), ZERO)))},
            "balance_sheet": {"assets": rows("asset", values), "liabilities": rows("liability", values), "equity": rows("equity", values), "retained_earnings": str(money(retained)), "total_assets": str(money(assets)), "total_liabilities_equity": str(money(liabilities + equity + retained)), "balanced": money(assets) == money(liabilities + equity + retained)},
            "cash_flow": {"opening": str(money(opening_cash["1000"] + opening_cash["1010"])), "inflows": str(money(cashflow["inflows"])), "outflows": str(money(cashflow["outflows"])), "net_change": str(money(cashflow["inflows"] - cashflow["outflows"])), "closing": str(money(values["1000"] + values["1010"]))}}


def product_margins(db, tenant_id, start=None, end=None):
    query = select(m.Document).where(m.Document.tenant_id == tenant_id, m.Document.status == "posted", m.Document.kind.in_(["sale", "sale_return"]))
    if start:
        query = query.where(m.Document.date >= start)
    if end:
        query = query.where(m.Document.date <= end)
    totals = defaultdict(lambda: {"quantity": ZERO, "revenue": ZERO, "cost": ZERO})
    for doc in db.scalars(query):
        sign = -1 if doc.kind == "sale_return" else 1
        for line in doc.payload["lines"]:
            row = totals[line["product_id"]]
            row["name"] = line["name"]
            row["quantity"] += sign * Decimal(line["quantity"])
            row["revenue"] += sign * Decimal(line["net"])
            row["cost"] += sign * Decimal(line["cost"])
    return [{"id": pid, "name": value["name"], "quantity": str(value["quantity"]), "revenue": str(money(value["revenue"])), "cost": str(money(value["cost"])), "profit": str(money(value["revenue"] - value["cost"])), "margin": str(money((value["revenue"] - value["cost"]) / value["revenue"] * 100)) if value["revenue"] else None} for pid, value in totals.items()]


def inventory_valuation(db, tenant_id, end=None):
    query = select(m.StockMovement).where(m.StockMovement.tenant_id == tenant_id, m.StockMovement.date <= (end or today()))
    totals = defaultdict(lambda: {"quantity": ZERO, "value": ZERO})
    for movement in db.scalars(query):
        row = totals[(movement.product_id, movement.warehouse_id)]
        row["quantity"] += movement.quantity
        row["value"] += movement.value
    result = []
    for (product_id, warehouse_id), row in totals.items():
        if not row["quantity"] and not row["value"]:
            continue
        product, warehouse = db.get(m.Product, product_id), db.get(m.Warehouse, warehouse_id)
        result.append({"id": f"{product_id}:{warehouse_id}", "product_id": product_id, "name": product.name, "sku": product.sku, "warehouse": warehouse.name, "warehouse_id": warehouse_id, "quantity": str(row["quantity"]), "value": str(money(row["value"])), "average_cost": str((row["value"] / row["quantity"]).quantize(Decimal("0.000001"))) if row["quantity"] else "0"})
    return result
