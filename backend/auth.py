"""Browser cookie sessions + CSRF protection; HTTP Basic for CLI use over TLS only."""
import base64
import binascii
import hashlib
import hmac
import os
import secrets
import time
from collections import defaultdict, deque
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from . import models
from .db import SessionLocal, get_db

SESSION_COOKIE = "interview_session"
ph = PasswordHasher(time_cost=2, memory_cost=65536, parallelism=2)
DUMMY_HASH = ph.hash("not-the-real-password-do-not-use")
_ATTEMPTS: dict[str, deque] = defaultdict(deque)


def now():
    return int(time.time())


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def verify(password: str, stored_hash: str) -> bool:
    try:
        return ph.verify(stored_hash, password)
    except (VerifyMismatchError, VerificationError, ValueError):
        return False


def bootstrap_admin():
    email = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
    password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "")
    with SessionLocal() as db:
        if db.scalar(select(models.User.id).limit(1)) is not None:
            return
        if not email or "@" not in email or len(password) < 14:
            raise RuntimeError("First boot requires BOOTSTRAP_ADMIN_EMAIL and a BOOTSTRAP_ADMIN_PASSWORD of at least 14 characters")
        db.add(models.User(email=email, password_hash=ph.hash(password), role="admin"))
        db.commit()


def login_rate_limit(ip_and_account: str):
    # Account-scoped safety net behind a reverse proxy: avoid a shared IP
    # exhausting the login budget for every employee. Keep ingress rate limits too.
    key = hashlib.sha256(ip_and_account.strip().lower().encode()).hexdigest()
    entries = _ATTEMPTS[key]
    current = now()
    while entries and entries[0] < current - 300:
        entries.popleft()
    if len(entries) >= 20:
        raise HTTPException(429, "Too many login attempts; retry later")
    entries.append(current)


def check_credentials(db: Session, email: str, password: str):
    account = db.scalar(select(models.User).where(models.User.email == email.lower()))
    if not account:
        verify(password, DUMMY_HASH)
        return None
    current = now()
    if account.locked_until > current or not account.is_active:
        return None
    if not verify(password, account.password_hash):
        account.failed_attempts += 1
        if account.failed_attempts >= 5:
            account.locked_until = current + 900
            account.failed_attempts = 0
        db.commit()
        return None
    account.failed_attempts = 0
    account.locked_until = 0
    db.commit()
    return account


def new_session(db: Session, user: models.User):
    token, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
    db.add(models.LoginSession(user_id=user.id, token_digest=digest(token), csrf_token=csrf,
                               created_at=now(), expires_at=now() + 8 * 60 * 60))
    db.commit()
    return token, csrf


def session_for_request(db: Session, request: Request):
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw or len(raw) > 256:
        return None
    record = db.scalar(select(models.LoginSession).where(models.LoginSession.token_digest == digest(raw)))
    if not record or record.expires_at <= now():
        return None
    user = db.get(models.User, record.user_id)
    if not user or not user.is_active or user.role not in ("admin", "recruiter"):
        return None
    return user, record


def require_admin(request: Request, db: Session = Depends(get_db)):
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("basic "):
        try:
            raw = base64.b64decode(authorization.split(" ", 1)[1], validate=True).decode("utf-8")
            email, password = raw.split(":", 1)
        except (ValueError, UnicodeError, binascii.Error):
            raise HTTPException(401, "Invalid HTTP Basic credentials", headers={"WWW-Authenticate": 'Basic realm="Interview Admin"'})
        login_rate_limit((request.client.host if request.client else "unknown") + ":" + email.lower())
        account = check_credentials(db, email, password)
        if not account:
            raise HTTPException(401, "Invalid credentials", headers={"WWW-Authenticate": 'Basic realm="Interview Admin"'})
        return account
    result = session_for_request(db, request)
    if not result:
        raise HTTPException(401, "Login required")
    user, session = result
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        submitted = request.headers.get("x-csrf-token", "")
        if not hmac.compare_digest(submitted, session.csrf_token):
            raise HTTPException(403, "CSRF verification failed")
    return user
