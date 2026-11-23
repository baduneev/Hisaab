import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from sqlalchemy import select
from .models import AuthSession, User


def password_hash(password: str):
    salt = secrets.token_hex(16)
    result = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1)
    return f"scrypt${salt}${result.hex()}"


def verify_password(password: str, encoded: str):
    try:
        _, salt, result = encoded.split("$")
        candidate = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()
        return hmac.compare_digest(candidate, result)
    except (ValueError, TypeError):
        return False


def new_session(db, user, hours):
    token = secrets.token_urlsafe(48)
    db.add(AuthSession(token_hash=hashlib.sha256(token.encode()).hexdigest(), user_id=user.id, expires_at=datetime.now(timezone.utc) + timedelta(hours=hours)))
    return token


def authenticated(db, token):
    if not token:
        raise HTTPException(401, "Sign in to continue")
    auth = db.get(AuthSession, hashlib.sha256(token.encode()).hexdigest())
    if not auth or auth.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(401, "Your session expired. Sign in again; your draft is preserved.")
    user = db.get(User, auth.user_id)
    if not user or not user.active:
        raise HTTPException(401, "This account is inactive")
    return user


FINANCE = {"Owner", "Accountant"}
READ_COSTS = {"Owner", "Accountant", "Viewer"}
OPERATIONS = {
    "Owner": None, "Accountant": None,
    "Sales": {"sale", "quotation", "receipt", "sale_return"},
    "Warehouse": {"goods_receipt", "transfer", "stock_adjustment", "purchase_return"},
    "Viewer": set(),
}


def require(user, roles):
    if user.role not in roles:
        raise HTTPException(403, "Your role does not allow this action. Ask your company owner for access.")


def allow_document(user, kind):
    allowed = OPERATIONS[user.role]
    if allowed is not None and kind not in allowed:
        raise HTTPException(403, "Your role does not allow this transaction")


def can_read_document(user, kind):
    return user.role in READ_COSTS or kind in (OPERATIONS.get(user.role) or set())
