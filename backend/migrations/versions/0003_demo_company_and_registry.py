"""Add demo-company metadata and safely tracked demo records."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0003_demo_company_and_registry"
down_revision = "0002_manufacturing_intelligence"
branch_labels = None
depends_on = None


def _columns(table):
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table)}


def _add_column(table, column):
    if column.name not in _columns(table):
        op.add_column(table, column)


def upgrade():
    _add_column(
        "customers",
        sa.Column("credit_limit", sa.Numeric(14, 2), nullable=False, server_default="0"),
    )
    _add_column("suppliers", sa.Column("gstin", sa.String(30), nullable=True))
    _add_column(
        "suppliers",
        sa.Column("payment_terms", sa.String(80), nullable=False, server_default="Due on receipt"),
    )
    tables = set(inspect(op.get_bind()).get_table_names())
    if "supplier_materials" not in tables:
        op.create_table(
            "supplier_materials",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("suppliers.id"), nullable=False),
            sa.Column("material_id", sa.Integer(), sa.ForeignKey("raw_materials.id"), nullable=False),
            sa.UniqueConstraint("supplier_id", "material_id"),
        )
    if "company_profiles" not in tables:
        op.create_table(
            "company_profiles",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(160), nullable=False, unique=True),
            sa.Column("address", sa.Text(), nullable=False),
            sa.Column("city", sa.String(100), nullable=False),
            sa.Column("state", sa.String(80), nullable=False),
            sa.Column("country", sa.String(80), nullable=False, server_default="India"),
            sa.Column("business", sa.String(240), nullable=False),
            sa.Column("demo_data", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if "demo_data_records" not in tables:
        op.create_table(
            "demo_data_records",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("batch_key", sa.String(80), nullable=False),
            sa.Column("entity_type", sa.String(80), nullable=False),
            sa.Column("entity_id", sa.String(80), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("batch_key", "entity_type", "entity_id"),
        )
    existing_indexes = {
        table: {index["name"] for index in inspect(op.get_bind()).get_indexes(table)}
        for table in ("supplier_materials", "demo_data_records")
    }
    if "ix_supplier_materials_supplier_id" not in existing_indexes["supplier_materials"]:
        op.create_index("ix_supplier_materials_supplier_id", "supplier_materials", ["supplier_id"])
    if "ix_supplier_materials_material_id" not in existing_indexes["supplier_materials"]:
        op.create_index("ix_supplier_materials_material_id", "supplier_materials", ["material_id"])
    if "ix_demo_data_records_batch_key" not in existing_indexes["demo_data_records"]:
        op.create_index("ix_demo_data_records_batch_key", "demo_data_records", ["batch_key"])


def downgrade():
    op.drop_index("ix_demo_data_records_batch_key", table_name="demo_data_records")
    op.drop_table("demo_data_records")
    op.drop_table("company_profiles")
    op.drop_index("ix_supplier_materials_material_id", table_name="supplier_materials")
    op.drop_index("ix_supplier_materials_supplier_id", table_name="supplier_materials")
    op.drop_table("supplier_materials")
    op.drop_column("suppliers", "payment_terms")
    op.drop_column("suppliers", "gstin")
    op.drop_column("customers", "credit_limit")
