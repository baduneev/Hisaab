"""Monitoring probe: non-zero exit when a tenant's journals or stock do not reconcile."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select
from api.config import settings
from api.models import Tenant, database
from api.reports import summary

engine, factory = database(settings.database_url)
results = []
with factory() as db:
    for tenant in db.scalars(select(Tenant)):
        report = summary(db, tenant.id)
        results.append({"tenant_id": tenant.id, **report["checks"]})
engine.dispose()
print(json.dumps(results, indent=2))
sys.exit(0 if all(x["journal_balanced"] and x["inventory_reconciled"] for x in results) else 1)
