import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .database import get_db
from .models import User


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


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 240_000)
    return f"{salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, expected = stored.split("$", 1)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 240_000).hex()
        return hmac.compare_digest(actual, expected)
    except ValueError:
        return False


def create_token(user: User) -> str:
    expires = datetime.now(timezone.utc) + timedelta(minutes=int(os.getenv("JWT_EXPIRE_MINUTES", "60")))
    return jwt.encode({"sub": str(user.id), "role": user.role, "exp": expires}, JWT_SECRET, algorithm=ALGORITHM)


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[ALGORITHM])
        user = db.get(User, int(payload["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if user is None or not user.active:
        raise HTTPException(status_code=401, detail="User is inactive or does not exist")
    return user


def require_roles(*roles: str):
    def dependency(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return dependency
