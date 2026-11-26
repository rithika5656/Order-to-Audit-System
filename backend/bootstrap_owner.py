import os
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import Base, SessionLocal, engine
from app.models import Role, User
from app.roles import OWNER
from app.security import hash_password


def create_initial_owner(db: Session, email: str, password: str) -> bool:
    email = email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValueError("INITIAL_OWNER_EMAIL must be a valid email address.")
    if (
        len(password) < 12
        or not re.search(r"[a-z]", password)
        or not re.search(r"[A-Z]", password)
        or not re.search(r"\d", password)
    ):
        raise ValueError(
            "INITIAL_OWNER_PASSWORD must be 12+ characters with uppercase, lowercase, and a number."
        )
    if db.scalar(select(User.id).limit(1)):
        return False

    if db.get(Role, OWNER) is None:
        db.add(Role(code=OWNER, description="NutriLedger owner"))
        db.flush()
    db.add(User(
        name="NutriLedger Owner",
        username=email.split("@", 1)[0][:80],
        email=email,
        password_hash=hash_password(password),
        role=OWNER,
        active=True,
        must_change_password=False,
    ))
    db.commit()
    return True


def main() -> None:
    email = os.getenv("INITIAL_OWNER_EMAIL")
    password = os.getenv("INITIAL_OWNER_PASSWORD")
    if not email or not password:
        raise RuntimeError(
            "Set INITIAL_OWNER_EMAIL and INITIAL_OWNER_PASSWORD in the deployment environment."
        )

    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        created = create_initial_owner(db, email, password)
    print("Initial owner account created." if created else "An account already exists; no owner was created.")


if __name__ == "__main__":
    main()
