from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import BomItem, Customer, InventoryMovement, Product, RawMaterial, Role, User
from app.security import hash_password


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)
    db = TestingSession()
    try:
        db.add_all([Role(code=role, description=role) for role in
                    ["Admin", "Salesman", "Production Supervisor", "Accountant / Auditor", "Owner"]])
        db.flush()
        user = User(name="Admin", email="admin@test.local", role="Admin", password_hash=hash_password("test-password"))
        salesperson = User(name="Sales", email="sales@test.local", role="Salesman", password_hash=hash_password("test-password"))
        product = Product(name="Murukku 200 g", sku="MUR-200", selling_price=Decimal("50"),
                          gst_rate=Decimal("5"), hsn_code="210690")
        db.add_all([
            user, salesperson, product,
            Customer(name="Retailer A", state="Tamil Nadu", customer_type="Retailer"),
            Customer(name="Distributor B", state="Karnataka", customer_type="Distributor"),
            RawMaterial(name="Flour", unit="kg", reorder_level=Decimal("20"), weighted_average_cost=Decimal("42")),
            RawMaterial(name="Cooking oil", unit="litre", reorder_level=Decimal("10"), weighted_average_cost=Decimal("140")),
            RawMaterial(name="Salt and spice mix", unit="kg", reorder_level=Decimal("2"), weighted_average_cost=Decimal("200")),
            RawMaterial(name="200 g pouch", unit="pieces", reorder_level=Decimal("100"), weighted_average_cost=Decimal("2.50")),
            RawMaterial(name="Carton", unit="pieces", reorder_level=Decimal("10"), weighted_average_cost=Decimal("15")),
        ])
        db.flush()
        materials = {m.name: m for m in db.query(RawMaterial).all()}
        for material_name, quantity in {
            "Flour": "100", "Cooking oil": "30", "Salt and spice mix": "5",
            "200 g pouch": "500", "Carton": "30",
        }.items():
            material = materials[material_name]
            db.add(InventoryMovement(
                item_type="material", item_id=material.id, quantity=Decimal(quantity),
                unit=material.unit, source_type="opening_balance", source_id=f"OPEN-{material.name}",
            ))
        db.add(InventoryMovement(item_type="finished", item_id=product.id, quantity=Decimal("50"),
                                 unit=product.unit, source_type="opening_balance", source_id="OPEN-MUR-200"))
        for material_name, quantity in {
            "Flour": "40", "Cooking oil": "10", "Salt and spice mix": "1.2",
            "200 g pouch": "200", "Carton": "10",
        }.items():
            db.add(BomItem(product_id=product.id, material_id=materials[material_name].id,
                           quantity=Decimal(quantity), per_output=Decimal("200")))
        db.commit()
        ids = {"product": product.id, "retailer": 1, "distributor": 2,
               **{name: material.id for name, material in materials.items()}}
    finally:
        db.close()

    def override_db():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        response = test_client.post("/api/auth/login", json={"email": "admin@test.local", "password": "test-password"})
        assert response.status_code == 200
        test_client.headers.update({"Authorization": f"Bearer {response.json()['access_token']}"})
        test_client.benchmark_ids = ids
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def test_full_benchmark_workflow(client):
    ids = client.benchmark_ids
    purchase = client.post("/api/purchases", json={
        "material_id": ids["Flour"], "quantity": "60", "unit_rate": "45", "reference": "PUR-BENCHMARK",
    })
    assert purchase.status_code == 200

    production = client.post("/api/production-runs", json={
        "product_id": ids["product"], "expected_output": 200, "good_output": 188,
        "damaged": 6, "reference": "RUN-BENCHMARK",
        "actual_consumption": {
            str(ids["Flour"]): "40", str(ids["Cooking oil"]): "10.5",
            str(ids["Salt and spice mix"]): "1.2", str(ids["200 g pouch"]): "188",
            str(ids["Carton"]): "9",
        },
    })
    assert production.status_code == 200, production.text
    assert Decimal(production.json()["yield_variance_percent"]) == Decimal("-6.000")
    assert Decimal(production.json()["consumption_variance"][str(ids["Cooking oil"])]) == Decimal("5.0")
    run_id = production.json()["id"]
    for category, amount, ref in [("Labour", "1200", "LAB-BENCH"), ("Gas and power", "600", "UTIL-BENCH")]:
        expense = client.post(f"/api/production-runs/{run_id}/expenses", json={
            "category": category, "amount": amount, "reference": ref,
        })
        assert expense.status_code == 200
    costing = client.get(f"/api/production-runs/{run_id}/costing")
    assert costing.status_code == 200
    assert costing.json()["raw_material_cost"] == "4055.00"
    assert costing.json()["overhead_cost"] == "1800.00"
    assert costing.json()["cost_per_packet"] == "31.14"

    retailer_order = client.post("/api/orders", json={
        "customer_id": ids["retailer"], "product_id": ids["product"], "quantity": 150,
    })
    assert retailer_order.status_code == 200
    order_id = retailer_order.json()["id"]
    assert client.post(f"/api/orders/{order_id}/approve").status_code == 200
    invoice_response = client.post(f"/api/orders/{order_id}/invoice")
    assert invoice_response.status_code == 200, invoice_response.text
    invoice = invoice_response.json()
    assert (invoice["taxable"], invoice["cgst"], invoice["sgst"], invoice["total"]) == (
        "7500.00", "187.50", "187.50", "7875.00"
    )
    assert client.post(f"/api/invoices/{invoice['id']}/dispatch", json={"quantity": 150}).status_code == 200
    payment = client.post(f"/api/invoices/{invoice['id']}/payments", json={
        "amount": "4000", "reference": "PAY-BENCHMARK",
    })
    assert payment.status_code == 200
    assert payment.json()["outstanding"] == "3875.00"
    exported = client.get("/api/reports/export/sales-register?format=csv")
    assert exported.status_code == 200
    assert "NL/" in exported.text
    assert client.get("/api/reports/export/production?format=xlsx").status_code == 200
    assert client.get("/api/reports/export/production?format=pdf").headers["content-type"] == "application/pdf"
    assert client.get(f"/api/invoices/{invoice['id']}/pdf").headers["content-type"] == "application/pdf"

    distributor_order = client.post("/api/orders", json={
        "customer_id": ids["distributor"], "product_id": ids["product"], "quantity": 120,
    })
    assert distributor_order.status_code == 200
    assert distributor_order.json()["shortage"] == "32"
    insufficient = client.post(f"/api/orders/{distributor_order.json()['id']}/approve")
    assert insufficient.status_code == 409
    assert "32 packet shortage" in insufficient.json()["detail"]

    inventory = client.get("/api/inventory").json()
    materials = {row["name"]: Decimal(row["quantity"]) for row in inventory["materials"]}
    goods = Decimal(inventory["finished_goods"][0]["quantity"])
    assert materials == {
        "Flour": Decimal("120.000"), "Cooking oil": Decimal("19.500"),
        "Salt and spice mix": Decimal("3.800"), "200 g pouch": Decimal("306.000"),
        "Carton": Decimal("21.000"),
    }
    assert goods == Decimal("88.000")
    invoice_date = client.get("/api/invoices").json()[0]["created_at"][:10]
    dashboard_response = client.get("/api/dashboard", params={
        "from_date": invoice_date, "to_date": invoice_date,
    })
    assert dashboard_response.status_code == 200
    dashboard = dashboard_response.json()
    assert dashboard["total_sales"] == "7500.00"
    assert dashboard["outstanding_receivables"] == "3875.00"
    assert dashboard["production_this_month"]["good_output"] == 188
    assert dashboard["active_production_runs"] == 0
    assert dashboard["pending_dispatch_count"] == 0
    assert dashboard["revenue_analytics"]["series"] == [{
        "date": invoice_date, "revenue": "7500.00",
    }]
    assert dashboard["production_performance"][0]["expected"] == 200
    assert dashboard["production_performance"][0]["actual"] == 188
    assert any(alert["type"] == "receivable" for alert in dashboard["attention"])


def test_dashboard_rejects_invalid_date_ranges(client):
    reversed_range = client.get("/api/dashboard", params={
        "from_date": "2026-03-02", "to_date": "2026-03-01",
    })
    too_wide = client.get("/api/dashboard", params={
        "from_date": "2024-01-01", "to_date": "2025-01-02",
    })
    assert reversed_range.status_code == 422
    assert too_wide.status_code == 422


def test_inventory_lots_policy_and_fefo_consumption(client):
    ids = client.benchmark_ids
    expiry = (date.today() + timedelta(days=45)).isoformat()
    purchase = client.post("/api/purchases", json={
        "material_id": ids["Flour"], "quantity": "5", "unit_rate": "45",
        "reference": "PUR-LOT-TEST", "batch_code": "FLOUR-BATCH-01",
        "expiry_date": expiry,
    })
    assert purchase.status_code == 200, purchase.text

    inventory = client.get("/api/inventory").json()
    flour = next(item for item in inventory["materials"] if item["id"] == ids["Flour"])
    assert flour["quantity"] == "105.000"
    assert flour["lots"][0]["batch_code"] == "FLOUR-BATCH-01"
    assert flour["lots"][0]["quantity"] == "5.000"

    policy = client.put(f"/api/inventory/material/{ids['Flour']}/policy", json={
        "minimum_stock": "120", "target_coverage_days": 14,
    })
    assert policy.status_code == 200
    assert policy.json()["low_stock"] is True

    production = client.post("/api/production-runs", json={
        "product_id": ids["product"], "expected_output": 200, "good_output": 200,
        "reference": "RUN-LOT-TEST",
        "actual_consumption": {
            str(ids["Flour"]): "102", str(ids["Cooking oil"]): "1",
            str(ids["Salt and spice mix"]): "0.1",
            str(ids["200 g pouch"]): "2", str(ids["Carton"]): "0.1",
        },
    })
    assert production.status_code == 200, production.text
    issue = next(row for row in client.get("/api/inventory/ledger").json()
                 if row["source_id"] == "RUN-LOT-TEST"
                 and row["item_type"] == "material" and row["item_id"] == ids["Flour"])
    assert issue["allocations"] == [{"batch_code": "FLOUR-BATCH-01", "quantity": "5.000"}], issue
    flour_after_issue = next(
        item for item in client.get("/api/inventory").json()["materials"]
        if item["id"] == ids["Flour"]
    )
    assert flour_after_issue["quantity"] == "3.000"
    assert flour_after_issue["lots"] == []

    next_run = client.post("/api/production-runs", json={
        "product_id": ids["product"], "expected_output": 200, "good_output": 200,
        "reference": "RUN-LEGACY-STOCK-TEST",
        "actual_consumption": {
            str(ids["Flour"]): "3", str(ids["Cooking oil"]): "1",
            str(ids["Salt and spice mix"]): "0.1",
            str(ids["200 g pouch"]): "2", str(ids["Carton"]): "0.1",
        },
    })
    assert next_run.status_code == 200, next_run.text


def test_expired_lots_are_not_issueable_stock(client):
    ids = client.benchmark_ids
    purchase = client.post("/api/purchases", json={
        "material_id": ids["Flour"], "quantity": "5", "unit_rate": "45",
        "reference": "PUR-EXPIRED-TEST", "batch_code": "EXPIRED-FLOUR",
        "expiry_date": (date.today() - timedelta(days=1)).isoformat(),
    })
    assert purchase.status_code == 200
    flour = next(item for item in client.get("/api/inventory").json()["materials"]
                 if item["id"] == ids["Flour"])
    assert flour["quantity"] == "105.000"
    assert flour["available_quantity"] == "100.000"
    assert flour["lots"][0]["expired"] is True

    failed_run = client.post("/api/production-runs", json={
        "product_id": ids["product"], "expected_output": 200, "good_output": 200,
        "reference": "RUN-EXPIRED-TEST",
        "actual_consumption": {
            str(ids["Flour"]): "101", str(ids["Cooking oil"]): "1",
            str(ids["Salt and spice mix"]): "0.1",
            str(ids["200 g pouch"]): "2", str(ids["Carton"]): "0.1",
        },
    })
    assert failed_run.status_code == 409


def test_role_restrictions_and_negative_inventory(client):
    login_response = client.post("/api/auth/login", json={"email": "sales@test.local", "password": "test-password"})
    assert login_response.status_code == 200
    client.headers.update({"Authorization": f"Bearer {login_response.json()['access_token']}"})
    forbidden = client.post("/api/purchases", json={
        "material_id": client.benchmark_ids["Flour"], "quantity": "1", "unit_rate": "1", "reference": "X",
    })
    assert forbidden.status_code == 403
    forbidden_policy = client.put(
        f"/api/inventory/material/{client.benchmark_ids['Flour']}/policy",
        json={"minimum_stock": "25", "target_coverage_days": 14},
    )
    assert forbidden_policy.status_code == 403
    client.headers.update({"Authorization": f"Bearer {client.post('/api/auth/login', json={'email': 'admin@test.local', 'password': 'test-password'}).json()['access_token']}"})
    failed_run = client.post("/api/production-runs", json={
        "product_id": client.benchmark_ids["product"], "expected_output": 200,
        "good_output": 188, "damaged": 0, "reference": "RUN-NEGATIVE",
        "actual_consumption": {
            str(client.benchmark_ids["Flour"]): "101", str(client.benchmark_ids["Cooking oil"]): "10",
            str(client.benchmark_ids["Salt and spice mix"]): "1.2",
            str(client.benchmark_ids["200 g pouch"]): "188", str(client.benchmark_ids["Carton"]): "9",
        },
    })
    assert failed_run.status_code == 409
    balances = client.get("/api/inventory").json()["materials"]
    flour = next(item for item in balances if item["name"] == "Flour")
    assert flour["quantity"] == "100.000"

