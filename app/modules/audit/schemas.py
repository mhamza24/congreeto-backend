"""
app/modules/audit/schemas.py

Pydantic schemas for the audit log API layer.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel


class AuditLogResponse(BaseModel):
    id: int
    tenant_public_id: Optional[str] = None
    user_public_id: Optional[str] = None
    user_name: Optional[str] = None
    entity_type: str
    entity_id: Optional[int] = None
    action: str
    diff: Dict[str, Any]
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}
