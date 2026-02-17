from uuid import UUID
from uuid6 import uuid7
from typing import List, Union, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from app.modules.chat import schemas as chat_schemas
import logging

logger = logging.getLogger(__name__)


def normalize_conversation(messages: Union[str, chat_schemas.ChatMessagePair, chat_schemas.ChatMessage, List[Union[str, chat_schemas.ChatMessagePair, chat_schemas.ChatMessage, Dict]]]) -> List[Dict]:
    normalized = []

    if not isinstance(messages, list):
        messages = [messages]

    for msg in messages:
        if isinstance(msg, str):
            normalized.append(
                {"role": chat_schemas.RoleEnum.USER.value, "content": msg})
        elif isinstance(msg, chat_schemas.ChatMessagePair):
            normalized.append(
                {"role": chat_schemas.RoleEnum.USER.value, "content": msg.user})
            normalized.append(
                {"role": chat_schemas.RoleEnum.ASSISTANT.value, "content": msg.assistant})
        elif isinstance(msg, chat_schemas.ChatMessage):
            normalized.append({"role": msg.role.value, "content": msg.content})
        elif isinstance(msg, dict):
            if "role" in msg and "content" in msg:
                normalized.append(msg)
            else:
                logger.error(f"Invalid dict message format: {msg}")
                raise ValueError(f"Invalid dict message: {msg}")
        else:
            logger.error(f"Unsupported message type: {type(msg)}")
            raise ValueError(f"Unsupported message type: {type(msg)}")

    return normalized
