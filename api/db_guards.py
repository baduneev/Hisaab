"""PostgreSQL guards complement API validation; run as part of schema migration."""
from sqlalchemy import text


def install_guards(connection):
    if connection.dialect.name != "postgresql":
        return
    connection.execute(text("""
      CREATE OR REPLACE FUNCTION hisaab_immutable() RETURNS trigger AS $$
      BEGIN
        IF TG_TABLE_NAME = 'documents' AND OLD.status <> 'posted' THEN
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END IF;
        RAISE EXCEPTION 'Posted accounting records and audit history are immutable';
      END; $$ LANGUAGE plpgsql;
    """))
    for table in ["documents", "journals", "ledger_lines", "stock_movements", "audit", "allocations"]:
        connection.execute(text(f"DROP TRIGGER IF EXISTS immutable_guard ON {table}"))
        connection.execute(text(f"CREATE TRIGGER immutable_guard BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION hisaab_immutable()"))
    connection.execute(text("""
      CREATE OR REPLACE FUNCTION hisaab_source_draft() RETURNS trigger AS $$
      DECLARE source_status text; source_tenant text;
      BEGIN
        IF TG_TABLE_NAME = 'ledger_lines' THEN
          SELECT d.status,d.tenant_id INTO source_status,source_tenant
          FROM documents d JOIN journals j ON j.document_id=d.id WHERE j.id=NEW.journal_id AND j.tenant_id=NEW.tenant_id;
        ELSE
          SELECT status,tenant_id INTO source_status,source_tenant FROM documents WHERE id=NEW.document_id;
        END IF;
        IF source_status IS DISTINCT FROM 'draft' OR source_tenant IS DISTINCT FROM NEW.tenant_id THEN
          RAISE EXCEPTION 'Accounting lines may only be added to a draft source in the same company';
        END IF;
        RETURN NEW;
      END; $$ LANGUAGE plpgsql;
    """))
    for table in ["journals", "ledger_lines", "stock_movements"]:
        connection.execute(text(f"DROP TRIGGER IF EXISTS source_draft_guard ON {table}"))
        connection.execute(text(f"CREATE TRIGGER source_draft_guard BEFORE INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION hisaab_source_draft()"))
    connection.execute(text("""
      CREATE OR REPLACE FUNCTION hisaab_balanced() RETURNS trigger AS $$
      DECLARE tid text; inventory numeric; control numeric; difference numeric;
      BEGIN
        tid := NEW.tenant_id;
        SELECT COALESCE(SUM(debit-credit),0) INTO difference FROM ledger_lines WHERE tenant_id=tid;
        IF difference <> 0 THEN RAISE EXCEPTION 'Ledger is unbalanced'; END IF;
        IF EXISTS (SELECT journal_id FROM ledger_lines WHERE tenant_id=tid GROUP BY journal_id HAVING SUM(debit-credit) <> 0) THEN
          RAISE EXCEPTION 'A journal is unbalanced';
        END IF;
        SELECT COALESCE(SUM(value),0) INTO inventory FROM stock WHERE tenant_id=tid;
        SELECT COALESCE(SUM(debit-credit),0) INTO control FROM ledger_lines WHERE tenant_id=tid AND account='1200';
        IF inventory <> control THEN RAISE EXCEPTION 'Inventory does not reconcile with the ledger'; END IF;
        IF EXISTS (
          SELECT s.id FROM stock s LEFT JOIN
          (SELECT product_id,warehouse_id,SUM(quantity) qty,SUM(value) val FROM stock_movements WHERE tenant_id=tid GROUP BY product_id,warehouse_id) mv
          ON s.product_id=mv.product_id AND s.warehouse_id=mv.warehouse_id
          WHERE s.tenant_id=tid AND (s.quantity<>COALESCE(mv.qty,0) OR s.value<>COALESCE(mv.val,0))
        ) THEN RAISE EXCEPTION 'Stock movements do not reconcile'; END IF;
        RETURN NEW;
      END; $$ LANGUAGE plpgsql;
    """))
    for table in ["documents", "stock", "ledger_lines", "stock_movements"]:
        connection.execute(text(f"DROP TRIGGER IF EXISTS balanced_guard ON {table}"))
        connection.execute(text(f"CREATE CONSTRAINT TRIGGER balanced_guard AFTER INSERT OR UPDATE ON {table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION hisaab_balanced()"))
