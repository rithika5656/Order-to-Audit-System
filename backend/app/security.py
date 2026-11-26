import os
import hashlib
import hmac
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .database import get_db
from .models import User
from .roles import canonical_role


JWT_SECRET = os.getenv("JWT_SECRET")
DEMO_MODE = os.getenv("DEMO_MODE", "true").lower() == "true"
INSECURE_SECRETS = {
    "", "development-secret-replace-before-deploying", "local-development-only-change-me",
    "generate-a-long-random-secret", "replace-this-with-a-long-random-secret",
}
if not DEMO_MODE and (JWT_SECRET is None or JWT_SECRET in INSECURE_SECRETS or len(JWT_SECRET) < 32):
    raise RuntimeError("Set a non-placeholder JWT_SECRET of at least 32 characters when DEMO_MODE is disabled.")
JWT_SECRET = JWT_SECRET or "local-development-only-change-me"
ALGORITHM = "HS256"
bearer = HTTPBearer(auto_error=False)
password_hasher = PasswordHasher(time_cost=3, memory_cost=32768, parallelism=2)


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, stored: str) -> bool:
    if stored.startswith("$argon2"):
        try:
            return password_hasher.verify(stored, password)
        except (VerificationError, InvalidHashError):
            return False
    try:
        salt, expected = stored.split("$", 1)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 240_000).hex()
        return hmac.compare_digest(actual, expected)
    except ValueError:
        return False


def create_token(user: User, remember_me: bool = False) -> str:
    if remember_me:
        expires = datetime.now(timezone.utc) + timedelta(days=int(os.getenv("JWT_REMEMBER_EXPIRE_DAYS", "14")))
    else:
        expires = datetime.now(timezone.utc) + timedelta(minutes=int(os.getenv("JWT_EXPIRE_MINUTES", "60")))
    return jwt.encode(
        {
            "sub": str(user.id),
            "role": canonical_role(user.role),
            "ver": user.token_version,
            "exp": expires,
        },
        JWT_SECRET,
        algorithm=ALGORITHM,
    )


def current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    token = credentials.credentials if credentials else request.cookies.get("nutriledger_access")
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        user = db.get(User, int(payload["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if user is None or not user.active:
        raise HTTPException(status_code=401, detail="User is inactive or does not exist")
    if payload.get("ver", 0) != user.token_version:
        raise HTTPException(status_code=401, detail="Session has been revoked")
    if payload.get("role") != canonical_role(user.role):
        raise HTTPException(status_code=401, detail="User permissions have changed; sign in again")
    return user


def require_roles(*roles: str):
    allowed = {canonical_role(role) for role in roles}

    def dependency(user: User = Depends(current_user)) -> User:
        if canonical_role(user.role) not in allowed:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return dependency
