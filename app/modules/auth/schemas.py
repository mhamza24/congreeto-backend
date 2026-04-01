# app/modules/chat/schemas.py
from fastapi import Query
from pydantic import BaseModel, ConfigDict, Field, EmailStr, field_validator
from typing import Any, Optional, List, Union, TypeVar, Generic
from datetime import datetime
from enum import Enum
from uuid import UUID
from app.modules.chat.models import ConversationStatus, MessageRole
from app.core.enums import UserStatus
DataT = TypeVar("DataT")

# ---------------------------------------------------------------------------
# Shared / primitives
# ---------------------------------------------------------------------------


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    sub: dict[str, Any]   # ← now a dict instead of plain str
    type: str             # "access" | "refresh"
    exp: int
# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class SignupRequest(BaseModel):
    email: EmailStr = Field(
        ...,                          # required — no default
        description="Globally unique. Lowercased before insert.",
    )
    password: str = Field(
        ...,
        min_length=8,                 # 1 is not safe — minimum 8 in production
        max_length=100,
        description="Plain-text. Hashed with bcrypt before storage. Never persisted raw.",
    )
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name:  str = Field(..., min_length=1, max_length=100)

    # status intentionally excluded — clients must never set their own status.
    # The service layer always forces UserStatus.INVITED on signup.

    # @field_validator("email")
    # @classmethod
    # def normalize_email(cls, v: str) -> str:
    #     return v.strip().lower()

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter.")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit.")
        return v

    model_config = ConfigDict(str_strip_whitespace=True)


class LoginRequest(BaseModel):
    email: EmailStr = Field(
        ...,                          # required — no default
        description="Email associated with the user account.",
    )
    password: str = Field(
        ...,
        description="Plain-text. Will be verified against the stored password hash.",
    )
    
class RefreshRequest(BaseModel):
    refresh_token: str
# ---------------------------------------------------------------------------
# Response schemas — messages
# ---------------------------------------------------------------------------

class SignupResponse(BaseModel):
    public_id: str
    message:   str = "Account created. Please verify your email."

    model_config = ConfigDict(from_attributes=True)


class LoginResponse(BaseModel):
    message: str = "Login successful."
    tokens: TokenPair


class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"