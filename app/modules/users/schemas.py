from __future__ import annotations

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field, field_validator
import re

from app.core.enums import UserStatus


# =============================================================================
# SHARED PRIMITIVES
# =============================================================================


# class UserBase(BaseModel):
#     email: str = EmailStr
#     first_name: str = Field(..., min_length=2, max_length=100)
#     last_name: str = Field(..., min_length=2, max_length=100)
#     avatar_url: str = Field(None,min_length=2, max_length=500)

  
#     model_config = ConfigDict(str_strip_whitespace=True)



# =============================================================================
# USER REQUEST SCHEMAS





#=============================================================================
# USER RESPONSE SCHEMAS

class UserProfileResponse(BaseModel):
    public_id:          str
    email:              EmailStr
    first_name:         str
    last_name:          str
    avatar_url:         Optional[str]
    status:             UserStatus
    email_verified_at:  Optional[datetime]   # ← raw datetime from DB
    last_login_at:      Optional[datetime]
    # settings:           dict
    # trial_ends_at:      Optional[datetime]
    created_at:         datetime
    updated_at:         datetime

    @computed_field
    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @computed_field
    @property
    def email_verified(self) -> bool:        # ← computed boolean for response
        return self.email_verified_at is not None

    model_config = ConfigDict(from_attributes=True)