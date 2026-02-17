from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import JSONResponse
from app.modules.chat import schemas as chat_schemas
from app.modules.chat import service as chat_service
from app.core.security import auth_barrier
from app.core.database import get_db
from app.core import exceptions
from app.core.response import ApiResponse, ErrorResponse
import logging

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/chat", tags=["Chat"])


# @router.post("/create_or_continue")
# async def chat(
#     payload: chat_schemas.TempChatCreateRequest,
#     #db: AsyncSession = Depends(get_db),
#     #user=Depends(auth_barrier),
# ):
#     payload.user_id = user.id  # enforce from token

#     convo = await service.create_chat_message(
#         db=db,
#         payload=payload,
#     )

#     return api_response(
#         data={
#             "chat_id": str(convo.chat_id),
#             "message_id": str(convo.id),
#         },
#         message="Chat processed successfully",
#         success=True,
#     )


@router.post("/create_or_continue")
async def chat_endpoint(payload: chat_schemas.TempChatCreateRequest):
    try:
        last_message = await chat_service.create_or_continue_chat(payload)
        return ApiResponse(
            data={
                "chat_id": str(last_message.chat_id),
                "message_id": str(last_message.message_id),
                "message": last_message.message,
            },
            message="Chat processed successfully",
            success=True,
        )
    except Exception as e:
        logging.error(f"Unexpected chat error: {e}")
        # Add sentry logging here
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                message="Could not process your request at this time. Please try again later.",
                detail=str(e)
            ).dict()
        )
