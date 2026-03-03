from fastapi import Query
from pydantic import BaseModel, Field
from typing import Dict, Optional, List, Union, TypeVar, Generic
from datetime import datetime
from enum import Enum
from uuid import UUID
from app.modules.chat.models import ConversationStatus, MessageRole

DataT = TypeVar("DataT")


class DashboardSummaryRequest(BaseModel):
    """
    get a summary of the dashboard data.
    """


class DashboardSummaryResponse(BaseModel):
    summary: Dict
