"""Preserve historical aging when advances are allocated later."""
from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    if "allocated_on" in {c["name"] for c in sa.inspect(connection).get_columns("allocations")}:
        return
    op.add_column("allocations", sa.Column("allocated_on", sa.Date(), nullable=True))
    if connection.dialect.name == "postgresql":
        connection.execute(sa.text("ALTER TABLE allocations DISABLE TRIGGER immutable_guard"))
    connection.execute(sa.text("UPDATE allocations SET allocated_on=(SELECT date FROM documents WHERE documents.id=allocations.payment_id)"))
    if connection.dialect.name == "postgresql":
        connection.execute(sa.text("ALTER TABLE allocations ENABLE TRIGGER immutable_guard"))
    op.alter_column("allocations", "allocated_on", nullable=False)


def downgrade():
    raise RuntimeError("Restore a verified backup to reverse accounting migrations")
