"""Initial accounting schema and database integrity guards."""
from alembic import op
from api.models import Base
from api.db_guards import install_guards

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    Base.metadata.create_all(op.get_bind())
    install_guards(op.get_bind())


def downgrade():
    raise RuntimeError("Accounting data migrations cannot be destructively downgraded. Restore a verified backup into a separate database.")
