from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Customer, Product, RawMaterial, Role, User
from app.roles import (
    ACCOUNTANT_AUDITOR, FACTORY_ADMIN, OWNER, PRODUCTION_SUPERVISOR, SALESMAN,
)
from app.security import hash_password


PASSWORD = "StrongTestPass123!"
TEST_USERS = (
    ("Owner", "owner@test.local", OWNER),
    ("Factory Admin", "factory-admin@test.local", FACTORY_ADMIN),
    ("Sales A", "sales-a@test.local", SALESMAN),
    ("Sales B", "sales-b@test.local", SALESMAN),
    ("Production", "production@test.local", PRODUCTION_SUPERVISOR),
    ("Auditor", "auditor@test.local", ACCOUNTANT_AUDITOR),
)


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)
    db = testing_session()
    try:
        db.add_all([Role(code=role, description=role) for role in (
            OWNER, FACTORY_ADMIN, SALESMAN, PRODUCTION_SUPERVISOR, ACCOUNTANT_AUDITOR,
        )])
        db.flush()
        users = [
            User(name=name, email=email, role=role, password_hash=hash_password(PASSWORD), active=True)
            for name, email, role in TEST_USERS
        ]
        db.add_all(users)
        db.flush()
        db.add_all([
            Customer(name="Assigned A", state="Tamil Nadu", customer_type="Retailer", assigned_user_id=users[2].id),
            Customer(name="Assigned B", state="Karnataka", customer_type="Retailer", assigned_user_id=users[3].id),
            Product(name="Test Snack", sku="TEST-001", selling_price=Decimal("50"), gst_rate=Decimal("5")),
            RawMaterial(name="Flour", unit="kg", weighted_average_cost=Decimal("3")),
        ])
        db.commit()
    finally:
        db.close()

    def override_db():
        session = testing_session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def sign_in(client, email, password=PASSWORD):
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    if response.status_code == 200:
        client.headers.update({"X-CSRF-Token": response.json()["csrf_token"]})
    return response


def test_cookie_login_logout_and_session_revocation(client):
    response = sign_in(client, "owner@test.local")
    assert response.status_code == 200
    assert response.json()["user"]["role"] == OWNER
    assert "access_token" not in response.json()
    assert "httponly" in response.headers["set-cookie"].lower()
    assert client.get("/api/auth/me").status_code == 200

    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_salesperson_data_scope_and_order_permissions(client):
    assert sign_in(client, "sales-a@test.local").status_code == 200
    customers = client.get("/api/customers")
    assert [customer["name"] for customer in customers.json()] == ["Assigned A"]
    order = client.post("/api/orders", json={"customer_id": 1, "product_id": 1, "quantity": 3})
    assert order.status_code == 200
    assert len(client.get("/api/orders").json()) == 1
    assert client.post(f"/api/orders/{order.json()['id']}/approve").status_code == 403

    assert sign_in(client, "sales-b@test.local").status_code == 200
    assert [customer["name"] for customer in client.get("/api/customers").json()] == ["Assigned B"]
    assert client.get("/api/orders").json() == []
    forbidden_order = client.post("/api/orders", json={"customer_id": 1, "product_id": 1, "quantity": 1})
    assert forbidden_order.status_code == 403


def test_production_and_accountant_server_side_boundaries(client):
    assert sign_in(client, "production@test.local").status_code == 200
    assert client.get("/api/production-schedule").status_code == 200
    inventory = client.get("/api/inventory")
    assert inventory.status_code == 200
    assert "weighted_average_cost" not in inventory.json()["materials"][0]
    assert client.get("/api/products").json()[0]["selling_price"] is None
    assert client.get("/api/dashboard").status_code == 403
    assert client.post("/api/invoices/1/payments", json={"amount": "1", "reference": "P-1"}).status_code == 403

    assert sign_in(client, "auditor@test.local").status_code == 200
    assert client.get("/api/reports/summary").status_code == 200
    assert client.get("/api/invoices").status_code == 200
    assert client.post("/api/invoices/1/payments", json={"amount": "1", "reference": "P-2"}).status_code == 403
    assert client.post("/api/production-runs", json={}).status_code == 403
    assert client.patch("/api/products/1", json={"selling_price": "55"}).status_code == 403

    assert sign_in(client, "factory-admin@test.local").status_code == 200
    updated = client.patch("/api/products/1", json={"selling_price": "55"})
    assert updated.status_code == 200
    assert updated.json()["selling_price"] == "55"


def test_login_rate_limit_password_reset_and_account_deactivation(client):
    for attempt in range(4):
        assert client.post("/api/auth/login", json={
            "email": "owner@test.local", "password": f"wrong-{attempt}",
        }).status_code == 401
    limited = client.post("/api/auth/login", json={"email": "owner@test.local", "password": "wrong-final"})
    assert limited.status_code == 429

    reset_request = client.post(
        "/api/auth/password-reset/request",
        json={"email": "factory-admin@test.local"},
    )
    assert reset_request.status_code == 200
    reset_token = reset_request.json()["development_token"]
    assert reset_token
    changed = client.post("/api/auth/password-reset", json={
        "email": "factory-admin@test.local",
        "token": reset_token,
        "new_password": "NewFactoryPass123!",
    })
    assert changed.status_code == 200
    reused = client.post("/api/auth/password-reset", json={
        "email": "factory-admin@test.local",
        "token": reset_token,
        "new_password": "AnotherFactory123!",
    })
    assert reused.status_code == 400
    assert sign_in(client, "factory-admin@test.local", "NewFactoryPass123!").status_code == 200

    admin_login = sign_in(client, "factory-admin@test.local", "NewFactoryPass123!")
    assert admin_login.status_code == 200
    created = client.post("/api/users", json={
        "name": "Inactive Sales", "username": "inactive-sales", "email": "inactive@test.local",
        "password": "TemporarySales123!", "role": SALESMAN,
    })
    assert created.status_code == 200
    assert created.json()["must_change_password"] is True
    deactivated = client.patch(f"/api/users/{created.json()['id']}", json={"active": False})
    assert deactivated.status_code == 200
    assert client.post("/api/auth/login", json={
        "email": "inactive@test.local", "password": "TemporarySales123!",
    }).status_code == 401
