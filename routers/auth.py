import hmac

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from config import settings
from core.security import (
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
    create_session_token,
    verify_session_token,
)

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


class SessionRequest(BaseModel):
    api_key: str = Field(..., min_length=1, description="Configured EvoScrapper API key")


def _cookie_secure(request: Request) -> bool:
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    return request.url.scheme == "https" or forwarded == "https"


def _set_session_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(request),
        path="/",
    )


@router.get("/status")
async def auth_status(request: Request) -> dict:
    """Reports whether authentication is required and if this browser has a session."""
    if not settings.API_KEY:
        return {"auth_required": False, "authenticated": True}
    return {
        "auth_required": True,
        "authenticated": verify_session_token(request.cookies.get(SESSION_COOKIE_NAME)),
    }


@router.post("/session")
async def create_session(
    payload: SessionRequest,
    request: Request,
    response: Response,
) -> dict:
    """Exchanges the API key for a short-lived HttpOnly browser session."""
    if not settings.API_KEY:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="API key authentication is not configured.",
        )
    if not hmac.compare_digest(payload.api_key, settings.API_KEY):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key.",
        )

    response.headers["Cache-Control"] = "no-store"
    _set_session_cookie(response, request, create_session_token())
    return {"status": "ok", "expires_in": SESSION_TTL_SECONDS}


@router.delete("/session")
async def delete_session(request: Request, response: Response) -> dict:
    """Clears the browser session cookie."""
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(request),
    )
    response.headers["Cache-Control"] = "no-store"
    return {"status": "ok", "authenticated": False}
