"""Run with HISAAB_TEST_DATABASE_URL set to a disposable PostgreSQL database URL."""
import os
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from conftest import post_doc

pytestmark = pytest.mark.skipif(not os.getenv("HISAAB_TEST_DATABASE_URL"), reason="PostgreSQL-only integrity/concurrency tests")


def test_concurrent_posts_do_not_oversell(client, trading):
    t = trading
    post_doc(client, "opening_stock", t, [{"product_id": t["product"], "quantity": "1", "unit_price": "100"}])
    ids = [client.post("/api/v1/documents", json={"kind": "sale", "date": t["date"], "contact_id": t["customer"], "warehouse_id": t["warehouse"], "lines": [{"product_id": t["product"], "quantity": "1", "unit_price": "200"}]}).json()["id"] for _ in range(2)]
    def post(index):
        return client.post(f"/api/v1/documents/{ids[index]}/post", headers={"Idempotency-Key": f"concurrent-sale-{index}"}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(post, [0, 1])) == [200, 409]
    report = client.get("/api/v1/reports/summary").json()
    assert Decimal(report["inventory_value"]) == 0
    assert report["checks"]["inventory_reconciled"]


def test_concurrent_same_key_creates_one_receipt(client, trading):
    doc = client.post("/api/v1/documents", json={"kind": "receipt", "date": trading["date"], "contact_id": trading["customer"], "amount": "1000"}).json()
    def post(_):
        return client.post(f"/api/v1/documents/{doc['id']}/post", headers={"Idempotency-Key": "same-concurrent-key"})
    with ThreadPoolExecutor(max_workers=3) as pool:
        responses = list(pool.map(post, range(3)))
    assert all(r.status_code == 200 for r in responses)
    assert len({r.json()["number"] for r in responses}) == 1
    assert Decimal(client.get("/api/v1/reports/summary").json()["cash"]) == 1000


def test_database_rejects_posted_document_edit(client, trading):
    doc = post_doc(client, "receipt", trading, contact_id=trading["customer"], amount="1000")
    with pytest.raises(DBAPIError):
        with client.app.state.engine.begin() as conn:
            conn.execute(text("UPDATE documents SET total=1 WHERE id=:id"), {"id": doc["id"]})


def test_database_rejects_unbalanced_direct_entry(client, trading):
    doc = post_doc(client, "receipt", trading, contact_id=trading["customer"], amount="1000")
    with pytest.raises(DBAPIError):
        with client.app.state.engine.begin() as conn:
            journal = conn.execute(text("SELECT id,tenant_id FROM journals WHERE document_id=:id"), {"id":doc["id"]}).first()
            conn.execute(text("INSERT INTO ledger_lines (id,tenant_id,journal_id,account,debit,credit) VALUES ('bad-entry',:tenant,:journal,'1000',1,0)"), {"tenant":journal.tenant_id,"journal":journal.id})


def test_database_rejects_balanced_append_to_posted_journal(client, trading):
    doc = post_doc(client,"receipt",trading,contact_id=trading["customer"],amount="1000")
    with pytest.raises(DBAPIError):
        with client.app.state.engine.begin() as conn:
            journal=conn.execute(text("SELECT id,tenant_id FROM journals WHERE document_id=:id"),{"id":doc["id"]}).first()
            conn.execute(text("INSERT INTO ledger_lines (id,tenant_id,journal_id,account,debit,credit) VALUES ('append-debit',:tenant,:journal,'1000',1,0), ('append-credit',:tenant,:journal,'3000',0,1)"),{"tenant":journal.tenant_id,"journal":journal.id})
