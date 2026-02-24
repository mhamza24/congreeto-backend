from fastapi import Query
from pydantic import BaseModel, Field
from typing import Optional, List, Union, TypeVar, Generic
from datetime import datetime
from enum import Enum
from uuid import UUID
from app.modules.chat.models import ConversationStatus, MessageRole

DataT = TypeVar("DataT")


class liveLinkScrapperRequest(BaseModel):
    link: str = Field(
        description="Live link for scrapping data",
    )


class liveLinkScrapperResponse(BaseModel):
    id: str = Field(description="unique identifier for the live link scrapper")
    status: str = Field(
        description="background task status: pending, completed, failed")
