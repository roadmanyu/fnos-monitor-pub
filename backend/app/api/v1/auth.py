from fastapi import APIRouter, HTTPException

from app.api.deps import create_access_token, verify_password
from app.config import get_config
from app.schemas.models import LoginRequest, TokenResponse

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=TokenResponse)
def login(body: LoginRequest):
    cfg = get_config()
    if body.username != cfg.auth.username or not verify_password(
        body.password, cfg.auth.password_hash
    ):
        raise HTTPException(
            status_code=401,
            detail={"code": "unauthorized", "message": "invalid credentials"},
        )
    token, expires = create_access_token(body.username)
    return TokenResponse(access_token=token, expires_in=expires)
