"""add source identity verification"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sources", sa.Column("identity_verified", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("sources", sa.Column("rejection_reason", sa.String(255), nullable=True))


def downgrade():
    op.drop_column("sources", "rejection_reason")
    op.drop_column("sources", "identity_verified")
