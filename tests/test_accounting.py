from decimal import Decimal as D
from concurrent.futures import ThreadPoolExecutor
from conftest import post_doc


def test_purchase_sale_collection_return_reconciles(client, trading):
    t = trading
    receipt = post_doc(client, "goods_receipt", t, [{"product_id": t["product"], "quantity": "10", "unit_price": "1000"}], contact_id=t["supplier"])
    post_doc(client, "purchase_bill", t, reference_id=receipt["id"], contact_id=t["supplier"])
    sale = post_doc(client, "sale", t, [{"product_id": t["product"], "quantity": "4", "unit_price": "1500"}], contact_id=t["customer"])
    post_doc(client, "receipt", t, contact_id=t["customer"], amount="2000", allocations=[{"document_id": sale["id"], "amount": "2000"}], account="1000")
    post_doc(client, "sale_return", t, [{"product_id": t["product"], "quantity": "1"}], reference_id=sale["id"], contact_id=t["customer"])
    report = client.get("/api/v1/reports/summary").json()
    assert D(report["receivables"]) == D("2500")
    assert D(report["payables"]) == D("10000")
    assert D(report["inventory_value"]) == D("7000")
    assert D(report["gross_profit"]) == D("1500")
    assert report["checks"]["journal_balanced"] is True
    assert report["checks"]["inventory_reconciled"] is True


def test_duplicate_post_is_idempotent_and_changed_request_conflicts(client, trading):
    t = trading
    draft = client.post("/api/v1/documents", json={"kind": "opening_stock", "date": t["date"], "warehouse_id": t["warehouse"], "lines": [{"product_id": t["product"], "quantity": "10", "unit_price": "100"}]}).json()
    path = f"/api/v1/documents/{draft['id']}/post"
    first = client.post(path, headers={"Idempotency-Key": "repeat-key-12345"})
    second = client.post(path, headers={"Idempotency-Key": "repeat-key-12345"})
    assert first.status_code == second.status_code == 200
    assert first.json()["number"] == second.json()["number"]
    assert D(client.get("/api/v1/stock").json()[0]["quantity"]) == 10
    assert client.patch(f"/api/v1/documents/{draft['id']}", json={"notes": "rewrite"}).status_code == 409


def test_goods_receipt_bill_does_not_duplicate_stock(client, trading):
    t = trading
    receipt = post_doc(client, "goods_receipt", t, [{"product_id": t["product"], "quantity": "10", "unit_price": "100"}], contact_id=t["supplier"])
    post_doc(client, "purchase_bill", t, contact_id=t["supplier"], reference_id=receipt["id"])
    assert D(client.get("/api/v1/stock").json()[0]["quantity"]) == 10
    r = client.post("/api/v1/documents", json={"kind": "purchase_bill", "date": t["date"], "contact_id": t["supplier"], "reference_id": receipt["id"]})
    assert client.post(f"/api/v1/documents/{r.json()['id']}/post", headers={"Idempotency-Key": "another-bill-key"}).status_code == 409


def test_negative_stock_rolls_back_all_entries(client, trading):
    t = trading
    r = client.post("/api/v1/documents", json={"kind": "sale", "date": t["date"], "contact_id": t["customer"], "warehouse_id": t["warehouse"], "lines": [{"product_id": t["product"], "quantity": "2", "unit_price": "1500"}]})
    doc_id = r.json()["id"]
    assert client.post(f"/api/v1/documents/{doc_id}/post", headers={"Idempotency-Key": "out-of-stock-key"}).status_code == 409
    assert client.get(f"/api/v1/documents/{doc_id}").json()["status"] == "draft"
    assert client.get("/api/v1/journals").json() == []


def test_customer_advance_and_allocation_limits(client, trading):
    t = trading
    post_doc(client, "receipt", t, contact_id=t["customer"], amount="3000", account="1000")
    statement = client.get(f"/api/v1/contacts/{t['customer']}/statement").json()
    assert D(statement["balance"]) == -3000
    assert D(statement["unallocated"]) == 3000


def test_returns_cannot_exceed_original_quantity(client, trading):
    t = trading
    post_doc(client, "opening_stock", t, [{"product_id": t["product"], "quantity": "10", "unit_price": "1000"}])
    sale = post_doc(client, "sale", t, [{"product_id": t["product"], "quantity": "1", "unit_price": "1500"}], contact_id=t["customer"])
    post_doc(client, "sale_return", t, [{"product_id": t["product"], "quantity": "1"}], reference_id=sale["id"], contact_id=t["customer"])
    r = client.post("/api/v1/documents", json={"kind": "sale_return", "date": t["date"], "reference_id": sale["id"], "contact_id": t["customer"], "warehouse_id": t["warehouse"], "lines": [{"product_id": t["product"], "quantity": "1"}]}).json()
    assert client.post(f"/api/v1/documents/{r['id']}/post", headers={"Idempotency-Key": "duplicate-return-key"}).status_code == 409


def test_weighted_average_and_transfer_preserve_valuation(client, trading):
    t = trading
    post_doc(client, "opening_stock", t, [{"product_id": t["product"], "quantity": "10", "unit_price": "100"}])
    post_doc(client, "goods_receipt", t, [{"product_id": t["product"], "quantity": "10", "unit_price": "200"}], contact_id=t["supplier"])
    second = client.post("/api/v1/warehouses", json={"name": "Pokhara", "branch": "Pokhara"}).json()
    post_doc(client, "transfer", t, [{"product_id": t["product"], "quantity": "4"}], destination_id=second["id"])
    stock = client.get("/api/v1/stock").json()
    assert sum(D(x["value"]) for x in stock) == 3000
    assert all(D(x["average_cost"]) == 150 for x in stock)


def test_locked_period_rejects_posting(client, trading):
    t = trading
    assert client.post("/api/v1/periods/lock", json={"through": t["date"]}).status_code == 200
    r = client.post("/api/v1/documents", json={"kind": "receipt", "date": t["date"], "contact_id": t["customer"], "amount": "20"}).json()
    assert client.post(f"/api/v1/documents/{r['id']}/post", headers={"Idempotency-Key": "locked-posting-key"}).status_code == 409


def test_unbalanced_journal_is_rejected(client, trading):
    r = client.post("/api/v1/documents", json={"kind": "journal", "date": trading["date"], "entries": [{"account": "1000", "debit": "100"}, {"account": "3000", "credit": "99"}]}).json()
    assert client.post(f"/api/v1/documents/{r['id']}/post", headers={"Idempotency-Key": "unbalanced-key-12"}).status_code == 422


def test_advance_can_be_allocated_to_a_later_invoice(client, trading):
    from datetime import date, timedelta
    t = trading
    earlier = {**t, "date": str(date.fromisoformat(t["date"]) - timedelta(days=2))}
    advance = post_doc(client, "receipt", earlier, contact_id=t["customer"], amount="2000")
    post_doc(client, "opening_stock", t, [{"product_id": t["product"], "quantity": "10", "unit_price": "1000"}])
    invoice = post_doc(client, "sale", t, [{"product_id": t["product"], "quantity": "1", "unit_price": "1500"}], contact_id=t["customer"])
    r = client.post(f"/api/v1/payments/{advance['id']}/allocate", json={"allocations": [{"document_id": invoice["id"], "amount": "1500"}]})
    assert r.status_code == 200, r.text
    assert D(client.get(f"/api/v1/documents/{invoice['id']}").json()["outstanding"]) == 0
    assert D(client.get(f"/api/v1/contacts/{t['customer']}/statement").json()["unallocated"]) == 500


def test_backdated_stock_rejected_and_invoice_sequence_resets_by_fiscal_year(client, trading):
    from datetime import date, timedelta
    t = trading
    post_doc(client, "opening_stock", t, [{"product_id": t["product"], "quantity": "10", "unit_price": "1000"}])
    r = client.post("/api/v1/documents", json={"kind": "goods_receipt", "date": str(date.fromisoformat(t["date"]) - timedelta(days=1)), "warehouse_id": t["warehouse"], "contact_id": t["supplier"], "lines": [{"product_id": t["product"], "quantity": "1", "unit_price": "1000"}]}).json()
    assert client.post(f"/api/v1/documents/{r['id']}/post", headers={"Idempotency-Key": "backdated-stock-key"}).status_code == 409
    first = post_doc(client, "receipt", {**t,"date":"2024-07-15"}, contact_id=t["customer"], amount="100")
    second = post_doc(client, "receipt", {**t,"date":"2024-07-16"}, contact_id=t["customer"], amount="100")
    assert "2080/81-00001" in first["number"]
    assert "2081/82-00001" in second["number"]
