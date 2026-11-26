"""Extend user profiles, secure auth records and salesperson assignments."""
import re

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "0004_secure_auth_and_sales_assignment"
down_revision = "0003_demo_company_and_registry"
branch_labels = None
depends_on = None


def _tables():
    return set(inspect(op.get_bind()).get_table_names())


def _columns(table):
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table)}


def _create_index(name, table, columns, unique=False):
    indexes = {index["name"] for index in inspect(op.get_bind()).get_indexes(table)}
    if name not in indexes:
        op.create_index(name, table, columns, unique=unique)


def upgrade():
    bind = op.get_bind()
    user_columns = _columns("users")
    additions = (
        sa.Column("username", sa.String(80), nullable=True),
        sa.Column("phone", sa.String(40), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    for column in additions:
        if column.name not in user_columns:
            op.add_column("users", column)

    used_usernames = set()
    for user_id, email in bind.execute(sa.text("SELECT id, email FROM users ORDER BY id")):
        base = re.sub(r"[^a-z0-9._-]+", "-", email.split("@", 1)[0].lower()).strip("-._")
        base = (base or f"user-{user_id}")[:70]
        username = base
        if username in used_usernames:
            username = f"{base[:69]}-{user_id}"
        used_usernames.add(username)
        bind.execute(
            sa.text(
                "UPDATE users SET username = :username, "
                "created_at = COALESCE(created_at, CURRENT_TIMESTAMP) WHERE id = :user_id"
            ),
            {"username": username, "user_id": user_id},
        )
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("users") as batch:
            batch.alter_column(
                "created_at",
                existing_type=sa.DateTime(),
                nullable=False,
                server_default=sa.func.current_timestamp(),
            )
    else:
        op.alter_column(
            "users",
            "created_at",
            existing_type=sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        )
    _create_index("ix_users_username", "users", ["username"], unique=True)

    if "assigned_user_id" not in _columns("customers"):
        column = sa.Column(
            "assigned_user_id", sa.Integer(),
            sa.ForeignKey("users.id", name="fk_customers_assigned_user_id_users"),
            nullable=True,
        )
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("customers") as batch:
                batch.add_column(column)
        else:
            op.add_column("customers", column)
    _create_index("ix_customers_assigned_user_id", "customers", ["assigned_user_id"])

    tables = _tables()
    if "login_activities" not in tables:
        op.create_table(
            "login_activities",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("email", sa.String(255), nullable=False),
            sa.Column("successful", sa.Boolean(), nullable=False),
            sa.Column("ip_address", sa.String(64), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        )
    _create_index("ix_login_activities_user_id", "login_activities", ["user_id"])
    _create_index("ix_login_activities_email", "login_activities", ["email"])
    _create_index("ix_login_activities_created_at", "login_activities", ["created_at"])

    if "login_attempts" not in tables:
        op.create_table(
            "login_attempts",
            sa.Column("identifier", sa.String(64), primary_key=True),
            sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("locked_until", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        )

    if "password_reset_tokens" not in tables:
        op.create_table(
            "password_reset_tokens",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("token_hash", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("used_at", sa.DateTime(), nullable=True),
        )
    _create_index("ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"])
    _create_index("ix_password_reset_tokens_token_hash", "password_reset_tokens", ["token_hash"], unique=True)

    bind.execute(
        sa.text("INSERT OR IGNORE INTO roles (code, description) VALUES (:code, :description)")
        if bind.dialect.name == "sqlite"
        else sa.text(
            "INSERT INTO roles (code, description) "
            "SELECT :code, :description WHERE NOT EXISTS "
            "(SELECT 1 FROM roles WHERE code = :code)"
        ),
        {"code": "Factory Admin", "description": "Factory operations and user administration"},
    )


def downgrade():
    op.drop_index("ix_password_reset_tokens_token_hash", table_name="password_reset_tokens")
    op.drop_index("ix_password_reset_tokens_user_id", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")
    op.drop_table("login_attempts")
    op.drop_index("ix_login_activities_created_at", table_name="login_activities")
    op.drop_index("ix_login_activities_email", table_name="login_activities")
    op.drop_index("ix_login_activities_user_id", table_name="login_activities")
    op.drop_table("login_activities")
    op.drop_index("ix_customers_assigned_user_id", table_name="customers")
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("customers") as batch:
            batch.drop_column("assigned_user_id")
    else:
        op.drop_column("customers", "assigned_user_id")
    op.drop_index("ix_users_username", table_name="users")
    for column in (
        "must_change_password", "token_version", "last_login_at",
        "created_at", "phone", "username",
    ):
        op.drop_column("users", column)
    op.execute("DELETE FROM roles WHERE code = 'Factory Admin'")
