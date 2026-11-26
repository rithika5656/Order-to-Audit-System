import os
import re
import secrets
from datetime import datetime

from sqlalchemy import select

from app.database import Base, SessionLocal, engine
from app.models import Customer, Role, User
from app.roles import (
    ACCOUNTANT_AUDITOR, FACTORY_ADMIN, OWNER, PRODUCTION_SUPERVISOR, SALESMAN,
)
from app.security import hash_password


ACCOUNTS = (
    ("NutriLedger Owner", "owner@nutriledger.demo", "owner.demo", OWNER, "DEMO_OWNER_PASSWORD"),
    ("Factory Administrator", "admin@nutriledger.demo", "factory.admin", FACTORY_ADMIN, "DEMO_FACTORY_ADMIN_PASSWORD"),
    ("NutriLedger Sales", "sales@nutriledger.demo", "sales.demo", SALESMAN, "DEMO_SALESMAN_PASSWORD"),
    ("Production Supervisor", "production@nutriledger.demo", "production.demo", PRODUCTION_SUPERVISOR, "DEMO_PRODUCTION_PASSWORD"),
    ("Accountant / Auditor", "auditor@nutriledger.demo", "auditor.demo", ACCOUNTANT_AUDITOR, "DEMO_AUDITOR_PASSWORD"),
)


def _password_for(environment_key):
    configured = os.getenv(environment_key)
    if configured:
        if (
            len(configured) < 12
            or not re.search(r"[a-z]", configured)
            or not re.search(r"[A-Z]", configured)
            or not re.search(r"\d", configured)
        ):
            raise ValueError(f"{environment_key} must be 12+ characters with uppercase, lowercase, and a number.")
        return configured
    return f"{secrets.token_urlsafe(24)}aA1!"


def seed_roles():
    if os.getenv("DEMO_MODE", "true").lower() != "true":
        raise RuntimeError("Refusing to seed role demo accounts when DEMO_MODE is disabled.")

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    created_credentials = []
    try:
        for name, email, username, role, _ in ACCOUNTS:
            if db.get(Role, role) is None:
                db.add(Role(code=role, description=f"{role} NutriLedger role"))
        db.flush()

        for name, email, username, role, environment_key in ACCOUNTS:
            if db.scalar(select(User.id).where(User.email == email)):
                print(f"Existing account left unchanged: {email}")
                continue
            if db.scalar(select(User.id).where(User.username == username)):
                raise RuntimeError(f"Username {username} is already assigned to another account.")
            password = _password_for(environment_key)
            db.add(User(
                name=name,
                username=username,
                email=email,
                password_hash=hash_password(password),
                role=role,
                active=True,
                created_at=datetime.utcnow(),
                must_change_password=False,
            ))
            created_credentials.append((email, password, role))

        db.flush()
        sales_user = db.scalar(select(User).where(User.email == "sales@nutriledger.demo"))
        if sales_user:
            for customer in db.scalars(select(Customer).where(Customer.assigned_user_id.is_(None))):
                customer.assigned_user_id = sales_user.id
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    if created_credentials:
        print("Generated one-time development credentials (save them securely):")
        for email, password, role in created_credentials:
            print(f"{role} | {email} | {password}")
    else:
        print("All requested demo accounts already exist; passwords were not changed or displayed.")


if __name__ == "__main__":
    seed_roles()
