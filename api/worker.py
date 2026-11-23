"""Durable job worker. Claims use SKIP LOCKED and work commits atomically with results."""
import base64
import logging
import time
from datetime import timedelta
from sqlalchemy import select
from . import models as m, imports, insights
from .config import settings
from .accounting import owned, tenant_lock
from .security import READ_COSTS
from .pdf import invoice_pdf

logger = logging.getLogger("hisaab.worker")


def run_one(factory):
    with factory.begin() as db:
        job = db.scalar(select(m.Job).where(m.Job.status == "pending", m.Job.attempts < 3).order_by(m.Job.created_at).with_for_update(skip_locked=True).limit(1))
        if job is None:
            return False
        user = owned(db, m.User, job.created_by, job.tenant_id)
        job.attempts += 1
        job.started_at = m.now()
        if not user.active or user.role not in READ_COSTS:
            job.status, job.result = "failed", {"error": "The requesting user no longer has access"}
            return True
        try:
            with db.begin_nested():
                if job.kind == "insights":
                    tenant_lock(db, job.tenant_id)
                    job.result = insights.snapshot(db, job.tenant_id)
                elif job.kind == "pdf":
                    doc = owned(db, m.Document, job.payload["document_id"], job.tenant_id)
                    tenant = db.get(m.Tenant, job.tenant_id)
                    contact = owned(db, m.Contact, doc.contact_id, job.tenant_id) if doc.contact_id else None
                    job.result = {"pdf_base64": base64.b64encode(invoice_pdf(tenant, doc, contact)).decode()}
                elif job.kind == "import":
                    if user.role not in {"Owner", "Accountant"}:
                        raise ValueError("Import permission was revoked")
                    batch = imports.commit(db, user, job.payload["batch_id"], f"job-import-{job.id}")
                    job.result = {"batch_id": batch.id, "rows": len(batch.rows)}
                job.status = "completed"
        except Exception:
            logger.exception("job_failed job_id=%s tenant_id=%s", job.id, job.tenant_id)
            job.status = "failed"
            job.result = {"error": "Job failed; review the record and retry with a new job"}
        return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    engine, factory = m.database(settings.database_url)
    try:
        while True:
            if not run_one(factory):
                time.sleep(2)
    except KeyboardInterrupt:
        engine.dispose()
