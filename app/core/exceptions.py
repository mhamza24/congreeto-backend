# app/exceptions.py  — your existing file, just add AuthError classes here

from typing import Optional

from fastapi import Request, HTTPException, Response, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError


# ── Handlers ──────────────────────────────────────────────────────────────────


async def http_exception_handler(request: Request, exc: HTTPException):
    
    # ← pass Basic Auth challenge through untouched so browser shows popup
    if exc.status_code == 401 and exc.headers and "WWW-Authenticate" in exc.headers:
        return Response(
            content=exc.detail,
            status_code=401,
            headers=dict(exc.headers),
        )

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "message": exc.detail,
            "data": None,
        },
    )
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = [
        {
            "field"  : " → ".join(str(loc) for loc in err["loc"]),
            "message": err["msg"],
            "type"   : err["type"],
        }
        for err in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "message": "Validation failed. Please check the fields below.",
            "data"   : errors,
        },
    )


# ── Base ──────────────────────────────────────────────────────────────────────

class AuthError(HTTPException):
    """All auth exceptions inherit from this. FastAPI catches it via http_exception_handler."""
    pass



# ── Auth exceptions ───────────────────────────────────────────────────────────

class EmailAlreadyExistsError(AuthError):
    def __init__(self, email: str):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An account with '{email}' already exists.",
        )

class InvalidCredentialsError(AuthError):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

class EmailNotVerifiedError(AuthError):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email not verified. Please check your inbox.",
        )

class AccountSuspendedError(AuthError):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been suspended. Contact support.",
        )

class InvalidOTPError(AuthError):
    def __init__(self, message: Optional[str] = None):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message or "Invalid or expired OTP code.",
        )

class OTPExpiredError(AuthError):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OTP has expired. Please request a new one.",
        )

class InvitationInvalidError(AuthError):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation link is invalid or has expired.",
        )


class InvalidTokenError(AuthError):
    def __init__(self, message: Optional[str] = None):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=message or "Invalid or expired token.",
        )


class RateLimitError(AuthError):
    def __init__(self, message: str = "Too many requests."):
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=message,
        )