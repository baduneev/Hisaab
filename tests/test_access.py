from conftest import post_doc


def test_other_tenant_cannot_read_or_reference_records(client, trading):
    customer_id = trading["customer"]
    client.post("/api/v1/auth/logout")
    r = client.post("/api/v1/auth/register", json={"company": "Other company", "name": "Other", "email": "other@test.np", "password": "Other-password-2026!"})
    assert r.status_code == 201
    assert client.get(f"/api/v1/contacts/{customer_id}/statement").status_code == 404
    r = client.post("/api/v1/documents", json={"kind": "receipt", "date": trading["date"], "contact_id": customer_id, "amount": "100"})
    assert r.status_code == 404


def test_viewer_cannot_post_and_warehouse_cannot_read_costs(client, trading):
    for role in ["Viewer", "Warehouse", "Sales"]:
        email = f"{role.lower()}@test.np"
        assert client.post("/api/v1/users", json={"name": role, "email": email, "password": "Role-password-2026!", "role": role}).status_code == 201
    client.post("/api/v1/auth/logout")
    client.post("/api/v1/auth/login", json={"email": "viewer@test.np", "password": "Role-password-2026!"})
    assert client.post("/api/v1/documents", json={"kind": "journal", "date": trading["date"]}).status_code == 403
    client.post("/api/v1/auth/logout")
    client.post("/api/v1/auth/login", json={"email": "warehouse@test.np", "password": "Role-password-2026!"})
    assert client.get("/api/v1/reports/summary").status_code == 403
    assert client.get("/api/v1/insights").status_code == 403
    assert client.get("/api/v1/products").status_code == 200
    assert all("average_cost" not in x for x in client.get("/api/v1/stock").json())


def test_tax_billing_fails_closed(client, trading):
    r = client.post("/api/v1/documents", json={"kind": "sale", "date": trading["date"], "tax_invoice": True, "contact_id": trading["customer"], "warehouse_id": trading["warehouse"], "lines": [{"product_id": trading["product"], "quantity": "1", "unit_price": "100", "tax_rate": "13"}]})
    assert r.status_code == 403


def test_unauthenticated_and_cross_origin_writes_rejected(client):
    assert client.post("/api/v1/contacts", json={"name": "Bad", "kind": "customer"}, headers={"Origin": "https://evil.test"}).status_code == 403
    client.post("/api/v1/auth/logout")
    assert client.get("/api/v1/contacts").status_code == 401


def test_warehouse_document_payload_does_not_leak_costs(client, trading):
    receipt = post_doc(client, "goods_receipt", trading, [{"product_id": trading["product"], "quantity": "10", "unit_price": "1234.56"}], contact_id=trading["supplier"])
    client.post("/api/v1/users", json={"name": "Warehouse user", "email": "stock@test.np", "password": "Warehouse-password!", "role": "Warehouse"})
    client.post("/api/v1/auth/logout")
    client.post("/api/v1/auth/login", json={"email": "stock@test.np", "password": "Warehouse-password!"})
    doc = client.get(f"/api/v1/documents/{receipt['id']}").json()
    assert "net" not in doc["payload"]
    assert "tax" not in doc["payload"]
    assert "unit_price" not in doc["payload"]["lines"][0]
    assert "1234.56" not in str(doc)
    assert client.get(f"/api/v1/documents/{receipt['id']}/pdf").status_code == 403


def test_viewer_cannot_replay_an_owners_posting_key(client, trading):
    draft = client.post("/api/v1/documents", json={"kind":"receipt", "date":trading["date"],"contact_id":trading["customer"],"amount":"100"}).json()
    path = f"/api/v1/documents/{draft['id']}/post"
    assert client.post(path,headers={"Idempotency-Key":"owner-replay-key"}).status_code == 200
    client.post("/api/v1/users",json={"name":"Read only","email":"readonly@test.np","password":"Readonly-password!","role":"Viewer"})
    client.post("/api/v1/auth/logout")
    client.post("/api/v1/auth/login",json={"email":"readonly@test.np","password":"Readonly-password!"})
    assert client.post(path,headers={"Idempotency-Key":"owner-replay-key"}).status_code == 403
