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


def verify_device_key(api_key: str, stored_hash: str) -> bool:
    return secrets.compare_digest(hash_device_key(api_key), stored_hash)


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    return password_hash.verify(password, stored_hash)


def create_access_token(username: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": username,
        "iss": "smart-fish-feeder",
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired access token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"], issuer="smart-fish-feeder")
        username = payload.get("sub")
        if not isinstance(username, str):
            raise credentials_error
    except InvalidTokenError as exc:
        raise credentials_error from exc
    user = db.scalar(select(User).where(User.username == username, User.active.is_(True)))
    if user is None:
        raise credentials_error
    return user
