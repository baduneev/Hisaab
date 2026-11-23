"""Prevent balanced append attacks on posted journals and stock documents."""
from alembic import op
from api.db_guards import install_guards

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade():
    install_guards(op.get_bind())


def downgrade():
    raise RuntimeError("Do not remove accounting integrity guards; restore into a separate database")
