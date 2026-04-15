from datetime import datetime
from http.client import HTTPException
from typing import Optional


def parse_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    if dt_str:
        try:
            return datetime.fromisoformat(
                dt_str
            )  # works with 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM:SS'
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid date format: {dt_str}. Use ISO format YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS",
            )
