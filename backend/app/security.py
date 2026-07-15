import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt import InvalidTokenError
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from .models import User

settings = get_settings()
password_hash = PasswordHash.recommended()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")


def hash_device_key(api_key: str) -> str:
    return hmac.new(settings.credential_pepper.encode(), api_key.encode(), hashlib.sha256).hexdigest()


def hash_pairing_code(pairing_code: str) -> str:
    normalized = pairing_code.strip().upper()
    return hmac.new(settings.credential_pepper.encode(), normalized.encode(), hashlib.sha256).hexdigest()


def verify_device_key(api_key: str, stored_hash: str) -> bool:
    return secrets.compare_digest(hash_device_key(api_key), stored_hash)


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    return password_hash.verify(password, stored_hash)


def create_access_token(user: User) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": user.username,
        "av": user.auth_version,
        "iss": "smart-fish-feeder",
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def create_account_action_token(user: User, purpose: str, expires_minutes: int) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": user.username,
        "uid": user.id,
        "purpose": purpose,
        "email": hashlib.sha256((user.email or "").encode()).hexdigest(),
        "pwd": hashlib.sha256(user.password_hash.encode()).hexdigest(),
        "iss": "smart-fish-feeder",
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_account_action_token(token: str, purpose: str) -> dict[str, object]:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"], issuer="smart-fish-feeder")
    except InvalidTokenError as exc:
        raise ValueError("This account link is invalid or has expired") from exc
    if payload.get("purpose") != purpose or not isinstance(payload.get("sub"), str):
        raise ValueError("This account link is not valid for the requested action")
    return payload


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired access token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"], issuer="smart-fish-feeder")
        username = payload.get("sub")
        auth_version = payload.get("av")
        if not isinstance(username, str) or not isinstance(auth_version, int):
            raise credentials_error
    except InvalidTokenError as exc:
        raise credentials_error from exc
    user = db.scalar(select(User).where(User.username == username, User.active.is_(True)))
    if user is None or user.auth_version != auth_version:
        raise credentials_error
    return user


def require_operator(user: User = Depends(get_current_user)) -> User:
    if user.role != "operator":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The public demo account cannot modify production resources",
        )
    return user


def require_customer(user: User = Depends(get_current_user)) -> User:
    if user.role != "customer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A customer account is required for device pairing",
        )
    return user


def require_account_user(user: User = Depends(get_current_user)) -> User:
    if user.role not in {"operator", "customer"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The public demo account cannot modify production resources",
        )
    return user
