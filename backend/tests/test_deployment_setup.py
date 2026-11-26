from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import pytest

from app.database import Base, normalize_database_url
from app.models import Role, User
from app.roles import OWNER
from app.security import verify_password
from bootstrap_owner import create_initial_owner


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("postgres://user:pass@host/db", "postgresql+psycopg://user:pass@host/db"),
        ("postgresql://user:pass@host/db", "postgresql+psycopg://user:pass@host/db"),
        ("postgresql+psycopg://user:pass@host/db", "postgresql+psycopg://user:pass@host/db"),
        ("sqlite:///./nutriledger.db", "sqlite:///./nutriledger.db"),
    ],
)
def test_normalize_database_url(url, expected):
    assert normalize_database_url(url) == expected


def test_initial_owner_bootstrap_is_idempotent_and_validates_password():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    with Session(engine) as db:
        assert create_initial_owner(db, "Owner@Example.com", "StrongOwnerPass123!") is True
        assert create_initial_owner(db, "other@example.com", "OtherOwnerPass123!") is False
        owner = db.scalar(select(User).where(User.role == OWNER))
        assert owner.email == "owner@example.com"
        assert verify_password("StrongOwnerPass123!", owner.password_hash)
        assert db.get(Role, OWNER) is not None
        with pytest.raises(ValueError, match="INITIAL_OWNER_PASSWORD"):
            create_initial_owner(db, "invalid@example.com", "weak")
    Base.metadata.drop_all(bind=engine)
