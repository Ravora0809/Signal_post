"""initial schema"""
from alembic import op
import sqlalchemy as sa


revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "companies",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("orgnr", sa.String(9), unique=True, index=True),
        sa.Column("name", sa.String(255), index=True),
        sa.Column("legal_form", sa.String(64)),
        sa.Column("registration_date", sa.String(32)),
        sa.Column("industry_code", sa.String(16)),
        sa.Column("industry_label", sa.String(255)),
        sa.Column("address", sa.String(255)),
        sa.Column("postal_code", sa.String(16)),
        sa.Column("city", sa.String(128)),
        sa.Column("country", sa.String(64)),
        sa.Column("website", sa.String(512)),
        sa.Column("raw", sa.JSON),
        sa.Column("created_at", sa.DateTime),
        sa.Column("updated_at", sa.DateTime),
    )

    op.create_table(
        "sources",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("company_id", sa.Integer, sa.ForeignKey("companies.id", ondelete="CASCADE")),
        sa.Column("url", sa.String(1024), index=True),
        sa.Column("url_canonical", sa.String(1024), index=True),
        sa.Column("url_hash", sa.String(64), index=True),
        sa.Column("content_hash", sa.String(64)),
        sa.Column("kind", sa.String(32)),
        sa.Column("fetched_at", sa.DateTime),
        sa.Column("status", sa.Integer),
        sa.Column("body", sa.Text),
        sa.UniqueConstraint("company_id", "url_hash", name="uq_source_company_urlhash"),
    )

    op.create_table(
        "facts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("company_id", sa.Integer, sa.ForeignKey("companies.id", ondelete="CASCADE"), index=True),
        sa.Column("key", sa.String(64), index=True),
        sa.Column("value_text", sa.Text),
        sa.Column("value_num", sa.Float),
        sa.Column("value_int", sa.BigInteger),
        sa.Column("currency", sa.String(8)),
        sa.Column("as_of", sa.DateTime),
        sa.Column("source_id", sa.Integer, sa.ForeignKey("sources.id", ondelete="SET NULL")),
        sa.Column("evidence_snippet", sa.Text),
        sa.Column("confidence", sa.Float, default=0.0),
        sa.Column("verified", sa.Boolean, default=False, index=True),
        sa.Column("conflict", sa.Boolean, default=False, index=True),
        sa.Column("observed_at", sa.DateTime, index=True),
        sa.Column("created_at", sa.DateTime),
    )
    op.create_index("ix_fact_company_key_observed", "facts", ["company_id", "key", "observed_at"])

    op.create_table(
        "fact_history",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("company_id", sa.Integer, sa.ForeignKey("companies.id", ondelete="CASCADE"), index=True),
        sa.Column("key", sa.String(64), index=True),
        sa.Column("old_value", sa.Text),
        sa.Column("new_value", sa.Text),
        sa.Column("change_type", sa.String(16)),
        sa.Column("detected_at", sa.DateTime, index=True),
    )

    op.create_table(
        "run_logs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("phase", sa.String(32), index=True),
        sa.Column("company_id", sa.Integer),
        sa.Column("status", sa.String(16)),
        sa.Column("message", sa.Text),
        sa.Column("requests_used", sa.Integer, default=0),
        sa.Column("cost_usd", sa.Float, default=0.0),
        sa.Column("duration_ms", sa.Integer, default=0),
        sa.Column("created_at", sa.DateTime, index=True),
    )


def downgrade():
    op.drop_table("run_logs")
    op.drop_table("fact_history")
    op.drop_index("ix_fact_company_key_observed", table_name="facts")
    op.drop_table("facts")
    op.drop_table("sources")
    op.drop_table("companies")