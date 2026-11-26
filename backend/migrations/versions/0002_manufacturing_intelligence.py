"""Add inventory lots, reorder policies and production state/plan fields."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0002_manufacturing_intelligence"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def _columns(table):
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table)}


def _add_column(table, column):
    if column.name not in _columns(table):
        if op.get_bind().dialect.name == "sqlite" and column.foreign_keys:
            with op.batch_alter_table(table) as batch_op:
                batch_op.add_column(column)
        else:
            op.add_column(table, column)


def upgrade():
    _add_column("products", sa.Column("reorder_level", sa.Numeric(14, 3), nullable=False, server_default="0"))
    _add_column("products", sa.Column("reorder_days", sa.Integer(), nullable=False, server_default="14"))
    _add_column("raw_materials", sa.Column("reorder_days", sa.Integer(), nullable=False, server_default="14"))
    _add_column("production_runs", sa.Column("status", sa.String(24), nullable=False, server_default="Completed"))
    _add_column("production_consumption", sa.Column(
        "expected_quantity", sa.Numeric(14, 3), nullable=False, server_default="0"
    ))

    tables = set(inspect(op.get_bind()).get_table_names())
    if "inventory_lots" not in tables:
        op.create_table(
            "inventory_lots",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("item_type", sa.String(24), nullable=False),
            sa.Column("item_id", sa.Integer(), nullable=False),
            sa.Column("batch_code", sa.String(80), nullable=False),
            sa.Column("expiry_date", sa.Date(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("item_type", "item_id", "batch_code", name="uq_inventory_lot_batch"),
        )
    _add_column("inventory_movements", sa.Column(
        "lot_id", sa.Integer(), sa.ForeignKey("inventory_lots.id"), nullable=True
    ))
    tables = set(inspect(op.get_bind()).get_table_names())
    if "inventory_lot_allocations" not in tables:
        op.create_table(
            "inventory_lot_allocations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("movement_id", sa.Integer(), sa.ForeignKey("inventory_movements.id"), nullable=False),
            sa.Column("lot_id", sa.Integer(), sa.ForeignKey("inventory_lots.id"), nullable=False),
            sa.Column("quantity", sa.Numeric(14, 3), nullable=False),
            sa.UniqueConstraint("movement_id", "lot_id", name="uq_lot_allocation_movement_lot"),
        )

    existing_indexes = {
        table: {index["name"] for index in inspect(op.get_bind()).get_indexes(table)}
        for table in ("inventory_lots", "inventory_movements", "inventory_lot_allocations", "production_runs")
    }
    indexes = (
        ("inventory_lots", "ix_inventory_lots_item_type", ["item_type"]),
        ("inventory_lots", "ix_inventory_lots_item_id", ["item_id"]),
        ("inventory_movements", "ix_inventory_movements_lot_id", ["lot_id"]),
        ("inventory_lot_allocations", "ix_inventory_lot_allocations_movement_id", ["movement_id"]),
        ("inventory_lot_allocations", "ix_inventory_lot_allocations_lot_id", ["lot_id"]),
        ("production_runs", "ix_production_runs_status", ["status"]),
    )
    for table, name, columns in indexes:
        if name not in existing_indexes[table]:
            op.create_index(name, table, columns)


def downgrade():
    op.drop_table("inventory_lot_allocations")
    op.drop_index("ix_inventory_movements_lot_id", table_name="inventory_movements")
    op.drop_column("inventory_movements", "lot_id")
    op.drop_table("inventory_lots")
    op.drop_index("ix_production_runs_status", table_name="production_runs")
    op.drop_column("production_runs", "status")
    op.drop_column("production_consumption", "expected_quantity")
    op.drop_column("raw_materials", "reorder_days")
    op.drop_column("products", "reorder_days")
    op.drop_column("products", "reorder_level")
