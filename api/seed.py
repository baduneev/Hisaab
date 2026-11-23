"""Explicit demo-only seed. Figures come from posted transactions, not UI constants."""
from datetime import timedelta
from sqlalchemy import select
from . import models as m
from .schemas import DocumentIn
from .accounting import create_document, post_document
from .security import password_hash
from .calendar import today


def seed_demo(db):
    if db.scalar(select(m.User.id).where(m.User.email == "owner@hisaab.demo")):
        return
    company = m.Tenant(name="Himalaya Trading Co.", address="Teku, Kathmandu, Nepal", demo=True)
    db.add(company)
    db.flush()
    owner = m.User(tenant_id=company.id, name="Aarav Shrestha", email="owner@hisaab.demo", password_hash=password_hash("Hisaab-demo-2026!"), role="Owner")
    db.add(owner)
    db.flush()
    main = m.Warehouse(tenant_id=company.id, name="Kathmandu warehouse", branch="Kathmandu")
    branch = m.Warehouse(tenant_id=company.id, name="Pokhara warehouse", branch="Pokhara")
    db.add_all([main, branch])
    names = ["Pokhara Mart", "Annapurna Stores", "Lumbini Wholesale", "Newa Supermarket", "Bhaktapur Fresh", "Everest Retail"]
    customers = [m.Contact(tenant_id=company.id, name=n, kind="customer", address=["Pokhara", "Kathmandu", "Butwal", "Lalitpur", "Bhaktapur", "Kathmandu"][i], phone=f"980000010{i}", credit_days=14) for i, n in enumerate(names)]
    supplier = m.Contact(tenant_id=company.id, name="Nepal Agro Suppliers", kind="supplier", address="Birgunj", credit_days=30)
    products = [m.Product(tenant_id=company.id, name=name, sku=sku, category=category, unit=unit, sale_price=price, reorder_level=reorder, pack_size=pack, pack_unit="carton") for name, sku, category, unit, price, reorder, pack in [
        ("Basmati rice · 25 kg bag", "RICE-25", "Grains", "bag", 2150, 30, 4),
        ("Sunflower oil · 1 litre", "OIL-01", "Cooking essentials", "bottle", 265, 40, 12),
        ("Masoor dal · 1 kg", "DAL-01", "Pulses", "packet", 195, 30, 20),
        ("Premium tea · 500 g", "TEA-05", "Beverages", "packet", 380, 20, 10),
        ("White sugar · 1 kg", "SUG-01", "Cooking essentials", "packet", 110, 50, 25),
        ("Wheat flour · 5 kg", "FLR-05", "Grains", "bag", 430, 25, 4),
    ]]
    db.add_all(customers + [supplier] + products)
    db.flush()
    start = today().replace(day=1) - timedelta(days=65)
    counter = 0
    def post(kind, day, **payload):
        nonlocal counter
        counter += 1
        data = DocumentIn.model_validate({"kind": kind, "date": str(day), "warehouse_id": main.id, **payload})
        doc = create_document(db, owner, data)
        return post_document(db, owner, doc.id, f"demo-seed-{counter:05d}")
    post("opening_balance", start, entries=[{"account": "1000", "debit": "125000"}, {"account": "1010", "debit": "480000"}, {"account": "3000", "credit": "605000"}])
    post("opening_stock", start, lines=[{"product_id": p.id, "quantity": str(qty), "unit_price": str(cost)} for p, qty, cost in zip(products, [250, 600, 400, 120, 450, 200], [1700, 205, 145, 280, 85, 330])])
    for day_offset in range(1, (today() - start).days + 1, 3):
        day = start + timedelta(days=day_offset)
        if day_offset % 18 == 1:
            gr = post("goods_receipt", day, contact_id=supplier.id, lines=[{"product_id": p.id, "quantity": str(15 if i == 0 else 25), "unit_price": str(cost)} for i, (p, cost) in enumerate(zip(products, [1700, 205, 145, 280, 85, 330]))])
            bill = post("purchase_bill", day, contact_id=supplier.id, reference_id=gr.id)
            if day < today() - timedelta(days=20):
                post("payment", day, contact_id=supplier.id, amount=str(bill.total), account="1010", allocations=[{"document_id": bill.id, "amount": str(bill.total)}])
        customer = customers[(day_offset // 3) % len(customers)]
        items = [{"product_id": p.id, "quantity": str((day_offset + i) % 6 + 2), "unit_price": str(p.sale_price)} for i, p in enumerate(products[:3])]
        invoice = post("sale", day, contact_id=customer.id, lines=items)
        if day_offset % 4 != 0 and day < today() - timedelta(days=5):
            amount = invoice.total if day_offset % 5 else invoice.total / 2
            post("receipt", day, contact_id=customer.id, amount=str(amount), account="1010" if day_offset % 2 else "1000", allocations=[{"document_id": invoice.id, "amount": str(amount)}])
    post("expense", today(), amount="18500", expense_account="6100", notes="Warehouse rent and utilities", account="1010")
    post("expense", today(), amount="4600", expense_account="6200", notes="Local delivery expenses")
    post("transfer", today(), destination_id=branch.id, lines=[{"product_id": products[0].id, "quantity": "30"}, {"product_id": products[1].id, "quantity": "50"}])
    # Reorder thresholds are explicit demo settings, displayed as sample data.
    products[0].reorder_level = 230
    products[1].reorder_level = 700
