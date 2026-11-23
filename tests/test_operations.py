from decimal import Decimal as D
from conftest import post_doc


def test_bs_ad_roundtrip_and_fiscal_boundary(client):
    r = client.get("/api/v1/calendar", params={"date": "2024-04-13", "calendar": "ad"})
    assert r.status_code == 200
    assert r.json()["bs"] == "2081-01-01"
    assert client.get("/api/v1/calendar", params={"date": "2081-01-01", "calendar": "bs"}).json()["ad"] == "2024-04-13"
    assert client.get("/api/v1/calendar", params={"date": "2024-07-15"}).json()["fiscal_year"] == "2080/81"
    assert client.get("/api/v1/calendar", params={"date": "2024-07-16"}).json()["fiscal_year"] == "2081/82"


def test_csv_preview_commit_and_duplicate_commit(client):
    csv = "name,sku,unit,sale_price,reorder_level\nBasmati rice,RICE,bag,1700,10\n"
    preview = client.post("/api/v1/imports/preview", json={"kind": "products", "csv": csv})
    assert preview.status_code == 200, preview.text
    assert preview.json()["valid"] is True
    key = preview.json()["id"]
    assert len(client.get("/api/v1/products").json()) == 0
    assert client.post(f"/api/v1/imports/{key}/commit", headers={"Idempotency-Key": "import-test-key"}).status_code == 200
    assert client.post(f"/api/v1/imports/{key}/commit", headers={"Idempotency-Key": "import-test-key"}).status_code == 200
    assert len(client.get("/api/v1/products").json()) == 1


def test_invalid_csv_cannot_be_committed(client):
    r = client.post("/api/v1/imports/preview", json={"kind": "products", "csv": "name,sku,sale_price\nRice,RICE,-2\n"})
    assert r.json()["valid"] is False
    assert client.post(f"/api/v1/imports/{r.json()['id']}/commit", headers={"Idempotency-Key": "invalid-import-key"}).status_code == 422


def test_insights_evidence_matches_summary_without_provider(client, trading):
    post_doc(client, "receipt", trading, contact_id=trading["customer"], amount="1000")
    data = client.get("/api/v1/insights").json()
    assert data["provider_status"] == "deterministic"
    assert data["metrics"]["cash"] == client.get("/api/v1/reports/summary").json()["cash"]
    assert data["as_of"]
    assert "limitations" in data
    answer = client.post("/api/v1/insights/ask", json={"question": "Who should I collect from?", "language": "ne"})
    assert answer.status_code == 200
    assert answer.json()["evidence"]


def test_bank_statement_match_is_exact_and_unique(client, trading):
    payment = post_doc(client, "receipt", trading, contact_id=trading["customer"], amount="1000", account="1010")
    uploaded = client.post("/api/v1/bank-statements", json={"csv": f"date,description,amount\n{trading['date']},Receipt,1000\n", "account": "1010"})
    assert uploaded.status_code == 201, uploaded.text
    row_id = uploaded.json()[0]["id"]
    assert client.post(f"/api/v1/bank-statements/{row_id}/match", json={"document_id": payment["id"]}).status_code == 200
    assert client.post(f"/api/v1/bank-statements/{row_id}/match", json={"document_id": payment["id"]}).status_code == 409


def test_invoice_pdf_and_trial_balance_exports(client, trading):
    post_doc(client, "opening_stock", trading, [{"product_id": trading["product"], "quantity": "10", "unit_price": "100"}])
    sale = post_doc(client, "sale", trading, [{"product_id": trading["product"], "quantity": "1", "unit_price": "200"}], contact_id=trading["customer"])
    pdf = client.get(f"/api/v1/documents/{sale['id']}/pdf")
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF-")
    report = client.get("/api/v1/reports/trial-balance").json()
    assert sum(D(x["debit"]) for x in report) == sum(D(x["credit"]) for x in report)


def test_historical_inventory_valuation_and_export(client, trading):
    post_doc(client, "opening_stock", trading, [{"product_id": trading["product"], "quantity": "10", "unit_price": "100"}])
    result = client.get("/api/v1/reports/inventory")
    assert result.status_code == 200
    assert sum(D(x["value"]) for x in result.json()) == 1000
    before = client.get("/api/v1/reports/inventory?end=2020-01-01")
    assert before.json() == []
    csv = client.get("/api/v1/reports/export?kind=inventory")
    assert csv.status_code == 200
    assert "average_cost" in csv.text


def test_suppliers_return_after_billing_reduces_payables_without_changing_profit(client, trading):
    t = trading
    receipt = post_doc(client, "goods_receipt", t, [{"product_id": t["product"], "quantity": "10", "unit_price": "1000"}], contact_id=t["supplier"])
    bill = post_doc(client, "purchase_bill", t, reference_id=receipt["id"], contact_id=t["supplier"])
    post_doc(client, "purchase_return", t, [{"product_id": t["product"], "quantity": "2"}], reference_id=receipt["id"], contact_id=t["supplier"])
    report = client.get("/api/v1/reports/summary").json()
    assert D(report["payables"]) == 8000
    assert D(report["inventory_value"]) == 8000
    assert D(client.get(f"/api/v1/documents/{bill['id']}").json()["outstanding"]) == 8000
    assert report["checks"]["inventory_reconciled"]


def test_pack_conversion_rounding_and_original_return_cost(client, trading):
    t = trading
    p = client.post("/api/v1/products", json={"name": "Tea packets", "sku": "TEA-PACK", "pack_size": "3", "sale_price": "1.00"}).json()
    post_doc(client, "opening_stock", t, [{"product_id": p["id"], "quantity": "1", "unit_price": "1.00", "unit": "pack"}])
    sale = post_doc(client, "sale", t, [{"product_id": p["id"], "quantity": "3", "unit_price": "0.50"}], contact_id=t["customer"])
    for _ in range(3):
        post_doc(client, "sale_return", t, [{"product_id": p["id"], "quantity": "1"}], reference_id=sale["id"], contact_id=t["customer"])
    report = client.get("/api/v1/reports/summary").json()
    assert D(report["inventory_value"]) == 1
    assert D(report["gross_profit"]) == 0
    assert report["checks"]["inventory_reconciled"]
