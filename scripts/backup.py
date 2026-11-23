"""Encrypted, snapshot-consistent PostgreSQL backups and non-destructive restore drills.

Run from the repository root with the local Compose database running. The encryption
key is loaded from the environment/.env and is never passed to a subprocess.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import psycopg
from cryptography.fernet import Fernet
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.config import settings


def connection_url(database=None):
    url = make_url(settings.database_url).set(drivername="postgresql")
    if database:
        url = url.set(database=database)
    return url.render_as_string(hide_password=False)


def compose_command(command, stdin=None):
    result = subprocess.run(["docker", "compose", "exec", "-T", "database", *command], input=stdin, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError("Database backup/restore command failed: " + result.stderr.decode(errors="replace")[:500])
    return result.stdout


def manifest(connection):
    tables = ["tenants", "users", "documents", "journals", "ledger_lines", "stock", "stock_movements", "allocations", "audit"]
    counts = {name: connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in tables}
    ledgers = connection.execute("SELECT tenant_id, SUM(debit-credit)::text FROM ledger_lines GROUP BY tenant_id ORDER BY tenant_id").fetchall()
    stocks = connection.execute("SELECT tenant_id, SUM(value)::text FROM stock GROUP BY tenant_id ORDER BY tenant_id").fetchall()
    if any(float(value) != 0 for _, value in ledgers):
        raise RuntimeError("Source ledger is unbalanced")
    return {"counts": counts, "ledger_balances": ledgers, "inventory_values": stocks}


def encryption():
    if not settings.encryption_key:
        raise RuntimeError("Set ENCRYPTION_KEY before creating or restoring a backup")
    return Fernet(settings.encryption_key.encode())


def create_backup(destination):
    url = make_url(settings.database_url)
    with psycopg.connect(connection_url()) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        snapshot = connection.execute("SELECT pg_export_snapshot()").fetchone()[0]
        info = manifest(connection)
        dump = compose_command(["pg_dump", "-U", url.username, "-d", url.database, "--format=custom", "--no-owner", "--no-acl", f"--snapshot={snapshot}"])
    payload = {"version": 1, "created_at": datetime.now(timezone.utc).isoformat(), "sha256": hashlib.sha256(dump).hexdigest(), "manifest": info, "dump": base64.b64encode(dump).decode()}
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    encrypted = encryption().encrypt(json.dumps(payload).encode())
    with path.open("xb") as file:
        file.write(encrypted)
    return {"path": str(path.resolve()), "encrypted": True, "bytes": len(encrypted), "manifest": info}


def restore_drill(source, database_name):
    if not re.fullmatch(r"hisaab_restore_[a-z0-9_]{1,40}", database_name):
        raise RuntimeError("Restore drills require a NEW database named hisaab_restore_<suffix>")
    url = make_url(settings.database_url)
    if database_name == url.database:
        raise RuntimeError("Refusing to overwrite the application database")
    payload = json.loads(encryption().decrypt(Path(source).read_bytes()))
    dump = base64.b64decode(payload["dump"])
    if hashlib.sha256(dump).hexdigest() != payload["sha256"]:
        raise RuntimeError("Backup checksum did not match")
    compose_command(["createdb", "-U", url.username, database_name])
    compose_command(["pg_restore", "-U", url.username, "-d", database_name, "--no-owner", "--no-acl", "--exit-on-error", "--single-transaction"], dump)
    with psycopg.connect(connection_url(database_name)) as connection:
        actual = manifest(connection)
        actual = json.loads(json.dumps(actual))
        if actual != payload["manifest"]:
            raise RuntimeError("Restored database did not match source manifest")
        mismatches = connection.execute("SELECT s.tenant_id FROM (SELECT tenant_id,SUM(value) value FROM stock GROUP BY tenant_id) s FULL JOIN (SELECT tenant_id,SUM(debit-credit) value FROM ledger_lines WHERE account='1200' GROUP BY tenant_id) l USING(tenant_id) WHERE COALESCE(s.value,0)<>COALESCE(l.value,0)").fetchall()
        if mismatches:
            raise RuntimeError("Restored inventory did not reconcile with the ledger")
    return {"restored_database": database_name, "checksum_verified": True, "manifest_matches": True, "inventory_reconciled": True, "manifest": actual}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    backup = commands.add_parser("create")
    backup.add_argument("--output", default=f"backups/hisaab-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.enc")
    restore = commands.add_parser("verify-restore")
    restore.add_argument("source")
    restore.add_argument("--database", required=True)
    args = parser.parse_args()
    try:
        result = create_backup(args.output) if args.command == "create" else restore_drill(args.source, args.database)
        print(json.dumps(result, indent=2))
    except Exception as exc:
        print(f"Backup operation failed: {exc}", file=sys.stderr)
        sys.exit(1)
