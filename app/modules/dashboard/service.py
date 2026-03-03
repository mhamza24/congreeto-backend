from __future__ import annotations
from fastapi import status
import json
import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import http_exception_handler
from app.modules.open_ai import service as openai_service
from app.modules.chat import tasks as background_tasks


from . import repository as repo
from . import schemas


logger = logging.getLogger(__name__)


async def fetch_summary(
    db: AsyncSession,
    #*,
    #payload: schemas.DashboardSummaryRequest,

) -> schemas.DashboardSummaryResponse:
    summary = await repo.get_dashboard_summary(db)
    return schemas.DashboardSummaryResponse(
        summary=summary
    )
