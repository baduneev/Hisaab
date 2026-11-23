import os
from datetime import date
import pytest
from fastapi.testclient import TestClient
from api.main import create_app


@pytest.fixture
def client(tmp_path):
    url = os.getenv("HISAAB_TEST_DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    admin = None
    if url.startswith("postgresql"):
        from sqlalchemy import create_engine, text
        from sqlalchemy.engine import make_url
        from uuid import uuid4
        database_name = "hisaab_test_" + uuid4().hex
        admin = create_engine(make_url(url).set(database="postgres"), isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{database_name}"'))
        url = make_url(url).set(database=database_name).render_as_string(hide_password=False)
    app = create_app(url, testing=True)
    with TestClient(app) as c:
        response = c.post("/api/v1/auth/register", json={"company": "Test Traders", "name": "Owner", "email": "owner@test.np", "password": "Test-password-2026!"})
        assert response.status_code == 201, response.text
        yield c
    if admin:
        from sqlalchemy import text
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{database_name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def trading(client):
    def create(path, payload):
        r = client.post(f"/api/v1/{path}", json=payload)
        assert r.status_code == 201, r.text
        return r.json()
    customer = create("contacts", {"name": "Pokhara Stores", "kind": "customer", "credit_days": 30})
    supplier = create("contacts", {"name": "Nepal Supply", "kind": "supplier"})
    product = create("products", {"name": "Rice 25kg", "sku": "RICE25", "unit": "bag", "sale_price": "1500", "reorder_level": "5"})
    warehouses = client.get("/api/v1/warehouses").json()
    return {"customer": customer["id"], "supplier": supplier["id"], "product": product["id"], "warehouse": warehouses[0]["id"], "date": date.today().isoformat()}


def post_doc(client, kind, context, lines=None, **extra):
    import uuid
    data = {"kind": kind, "date": context["date"], "warehouse_id": context["warehouse"], "lines": lines or [], **extra}
    r = client.post("/api/v1/documents", json=data)
    assert r.status_code == 201, r.text
    r = client.post(f"/api/v1/documents/{r.json()['id']}/post", headers={"Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code == 200, r.text
    return r.json()
