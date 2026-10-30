from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_config

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(plain, hashed)
    except Exception:
        return False


def create_access_token(subject: str) -> tuple[str, int]:
    cfg = get_config()
    expire_sec = cfg.auth.jwt_expire_sec
    exp = datetime.now(timezone.utc) + timedelta(seconds=expire_sec)
    token = jwt.encode(
        {"sub": subject, "exp": exp},
        cfg.auth.jwt_secret,
        algorithm="HS256",
    )
    return token, expire_sec


def require_user(
    creds: HTTPAuthorizationCredentials | None = Depends(security),
) -> str:
    cfg = get_config()
    if creds is None or not creds.credentials:
        raise HTTPException(status_code=401, detail={"code": "unauthorized", "message": "missing token"})
    try:
        payload = jwt.decode(creds.credentials, cfg.auth.jwt_secret, algorithms=["HS256"])
        sub = payload.get("sub")
        if not sub:
            raise HTTPException(status_code=401, detail={"code": "unauthorized", "message": "invalid token"})
        return str(sub)
    except JWTError:
        raise HTTPException(status_code=401, detail={"code": "unauthorized", "message": "invalid token"})
