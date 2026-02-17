# app/modules/chat/api.py

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.chat.schemas import ChatCreateRequest
from app.modules.chat import service
from app.core.security import auth_barrier
from app.core.database import get_db


router = APIRouter(prefix="/chat", tags=["Chat"])


# @router.post("/")
# async def chat(
#     payload: ChatCreateRequest,
#     db: AsyncSession = Depends(get_db),
#     user=Depends(auth_barrier),
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
