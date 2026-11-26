import os
import sqlite3
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from textwrap import dedent


BACKEND = Path(__file__).resolve().parents[1]


def run_command(database_url, *args, demo_mode="true"):
    env = os.environ.copy()
    env.update({
        "DATABASE_URL": database_url,
        "JWT_SECRET": "isolated-demo-test-secret",
        "DEMO_MODE": demo_mode,
    })
    return subprocess.run(
        [sys.executable, *args],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_demo_seed_is_consistent_idempotent_and_safely_reset(tmp_path):
    database_path = tmp_path / "demo.sqlite"
    database_url = f"sqlite:///{database_path.as_posix()}"
    migration = run_command(database_url, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head")
    assert migration.returncode == 0, migration.stderr

    seeded = run_command(database_url, "seed_demo.py")
    assert seeded.returncode == 0, seeded.stderr
    assert "Tagged demo records: 768 total, 204 stock movements, 130 audit activities." in seeded.stdout
    reseeded = run_command(database_url, "seed_demo.py")
    assert reseeded.returncode == 0, reseeded.stderr
    assert "already exists; no changes made" in reseeded.stdout
    unconfirmed_reset = run_command(database_url, "reset_demo.py")
    assert unconfirmed_reset.returncode != 0
    assert "requires --confirm" in unconfirmed_reset.stderr
    disabled_reset = run_command(database_url, "reset_demo.py", "--confirm", demo_mode="false")
    assert disabled_reset.returncode != 0
    assert "DEMO_MODE is disabled" in disabled_reset.stderr

    with sqlite3.connect(database_path) as connection:
        expected_counts = {
            "products": 10,
            "raw_materials": 15,
            "customers": 8,
            "suppliers": 10,
            "users": 5,
            "orders": 35,
            "production_runs": 18,
            "purchases": 12,
            "invoices": 28,
            "payments": 15,
        }
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in expected_counts
        }
        assert counts == expected_counts
        assert connection.execute("SELECT COUNT(*) FROM bom_items").fetchone()[0] >= 10
        assert connection.execute("SELECT COUNT(*) FROM inventory_movements").fetchone()[0] >= 20
        assert connection.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0] >= 30
        assert connection.execute(
            "SELECT COUNT(*) FROM demo_data_records WHERE batch_key = 'sri-lakshmi-foods-demo-v1'"
        ).fetchone()[0] >= sum(expected_counts.values())

        invalid_invoices = connection.execute(
            """SELECT COUNT(*) FROM invoices i JOIN orders o ON o.id = i.order_id
               WHERE o.status IN ('Submitted', 'Rejected')"""
        ).fetchone()[0]
        assert invalid_invoices == 0

        for taxable, cgst, sgst, igst, state in connection.execute(
            """SELECT i.taxable, i.cgst, i.sgst, i.igst, c.state
               FROM invoices i JOIN orders o ON o.id = i.order_id
               JOIN customers c ON c.id = o.customer_id"""
        ):
            base = Decimal(str(taxable))
            if state == "Tamil Nadu":
                assert Decimal(str(cgst)) == (base * Decimal("0.025")).quantize(Decimal("0.01"))
                assert Decimal(str(sgst)) == (base * Decimal("0.025")).quantize(Decimal("0.01"))
                assert Decimal(str(igst)) == 0
            else:
                assert Decimal(str(igst)) == (base * Decimal("0.05")).quantize(Decimal("0.01"))
                assert Decimal(str(cgst)) == 0
                assert Decimal(str(sgst)) == 0

        for invoice_total, paid in connection.execute(
            """SELECT i.total, COALESCE(SUM(p.amount), 0)
               FROM invoices i LEFT JOIN payments p ON p.invoice_id = i.id
               GROUP BY i.id"""
        ):
            assert Decimal(str(paid)) <= Decimal(str(invoice_total))

        negative_balances = connection.execute(
            """SELECT COUNT(*) FROM (
                 SELECT item_type, item_id, SUM(quantity) AS balance
                 FROM inventory_movements GROUP BY item_type, item_id
                 HAVING balance < 0
               )"""
        ).fetchone()[0]
        assert negative_balances == 0

        for reference, material_id, quantity in connection.execute(
            "SELECT reference, material_id, quantity FROM purchases"
        ):
            received = connection.execute(
                """SELECT COALESCE(SUM(quantity), 0) FROM inventory_movements
                   WHERE source_type = 'purchase' AND source_id = ?
                     AND item_type = 'material' AND item_id = ?""",
                (reference, material_id),
            ).fetchone()[0]
            assert Decimal(str(received)) == Decimal(str(quantity))

        for reference, product_id, good_output in connection.execute(
            "SELECT reference, product_id, good_output FROM production_runs"
        ):
            produced = connection.execute(
                """SELECT COALESCE(SUM(quantity), 0) FROM inventory_movements
                   WHERE source_type = 'production' AND source_id = ?
                     AND item_type = 'finished' AND item_id = ?""",
                (reference, product_id),
            ).fetchone()[0]
            assert Decimal(str(produced)) == Decimal(good_output)
            for material_id, consumed in connection.execute(
                """SELECT material_id, quantity FROM production_consumption
                   WHERE production_run_id = (
                     SELECT id FROM production_runs WHERE reference = ?
                   )""",
                (reference,),
            ):
                ledger_consumed = connection.execute(
                    """SELECT -COALESCE(SUM(quantity), 0) FROM inventory_movements
                       WHERE source_id = ? AND item_type = 'material' AND item_id = ?
                         AND source_type IN ('production', 'production-damage')""",
                    (reference, material_id),
                ).fetchone()[0]
                assert Decimal(str(ledger_consumed)) == Decimal(str(consumed))

        for reference, quantity in connection.execute(
            "SELECT reference, quantity FROM dispatches"
        ):
            shipped = connection.execute(
                """SELECT -COALESCE(SUM(quantity), 0) FROM inventory_movements
                   WHERE source_type = 'dispatch' AND source_id = ? AND item_type = 'finished'""",
                (reference,),
            ).fetchone()[0]
            assert Decimal(str(shipped)) == Decimal(quantity)

        benchmark_rows = connection.execute(
            "SELECT COUNT(*) FROM products WHERE name = 'Murukku 200 g'"
        ).fetchone()[0]
        assert benchmark_rows == 0

    api_checks = run_command(database_url, "-c", dedent("""
        from fastapi.testclient import TestClient
        from sqlalchemy import select
        from app.database import SessionLocal
        from app.main import app
        from app.models import User
        from app.security import create_token

        with SessionLocal() as db:
            admin = db.scalar(select(User).where(User.email == "demo.admin@srilakshmifoods.example.test"))
            token = create_token(admin)
        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {token}"}
            dashboard = client.get("/api/dashboard", headers=headers)
            assert dashboard.status_code == 200, dashboard.text
            data = dashboard.json()
            assert data["company"]["name"] == "Sri Lakshmi Foods"
            assert data["total_orders"] == 35
            assert data["monthly_production"] and data["monthly_payments"]
            assert data["monthly_wastage"] and data["top_selling_products"]
            assert data["pending_customer_payments"]
            assert client.get("/api/customers", headers=headers).json()[0]["outstanding_balance"] is not None
            assert len(client.get("/api/suppliers", headers=headers).json()) == 10
            order_rows = client.get("/api/orders", headers=headers).json()
            assert len(order_rows) == 35
            assert any(row["payment_status"] == "Partially paid" for row in order_rows)
    """))
    assert api_checks.returncode == 0, api_checks.stderr + api_checks.stdout

    with sqlite3.connect(database_path) as connection:
        customer_id, product_id = connection.execute(
            "SELECT customer_id, product_id FROM orders LIMIT 1"
        ).fetchone()
        connection.execute(
            """INSERT INTO users (name, email, password_hash, role, active)
               VALUES ('Real User', 'real@example.test', 'not-a-login-hash', 'Admin', 1)"""
        )
        real_user_id = connection.execute(
            "SELECT id FROM users WHERE email = 'real@example.test'"
        ).fetchone()[0]
        connection.execute(
            """INSERT INTO orders
               (reference, customer_id, product_id, quantity, unit_price, status, created_by, created_at)
               VALUES ('REAL-ORDER-KEEP', ?, ?, 1, 1, 'Submitted', ?, '2026-01-01 00:00:00')""",
            (customer_id, product_id, real_user_id),
        )
        connection.commit()

    blocked_reset = run_command(database_url, "reset_demo.py", "--confirm")
    assert blocked_reset.returncode != 0
    assert "non-demo orders" in blocked_reset.stderr

    with sqlite3.connect(database_path) as connection:
        connection.execute("DELETE FROM orders WHERE reference = 'REAL-ORDER-KEEP'")
        connection.commit()

    reset = run_command(database_url, "reset_demo.py", "--confirm")
    assert reset.returncode == 0, reset.stderr
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM demo_data_records").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM users WHERE id = ?", (real_user_id,)).fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0
