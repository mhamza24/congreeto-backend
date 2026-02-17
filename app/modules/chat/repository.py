from sqlalchemy import select
from app.modules.chat.models import Conversation
from app.core.database import AsyncSessionLocal

class ChatRepository:

    async def create_conversation(self, message: str, response: str):
        async with AsyncSessionLocal() as session:
            convo = Conversation(message=message, response=response)
            session.add(convo)
            await session.commit()
            await session.refresh(convo)
            return convo
