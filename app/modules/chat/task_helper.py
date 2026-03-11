from app.core.database import get_db, get_task_db_session
import asyncio
import json
from app.utils.system_prompt_chat_analysis import system_prompt_extract_chat_insights, system_prompt_veloce_website_insights
from app.config.settings import get_settings
from app.config.celery_worker import celery_app, QUEUEEnum
from app.modules.open_ai import service as ai_service
from app.modules.chat import schemas as chat_schema
from app.modules.email import service as email_service
import logging
from . import repository as repo
import logging
logger = logging.getLogger(__name__)


async def run_analysis(conversation__id: int, tenant_id: str) -> dict:
    async with get_task_db_session() as db:
        messages = await repo.get_conversation_history(
            db,
            conversation__id=conversation__id,
        )

        formatted_messages = [
            {"role": msg.role.value, "content": msg.content}
            for msg in messages
        ]
        if tenant_id is "veloce_website":
            raw_response = await ai_service.openai_call_conversation_analysis(
                formatted_messages,
                json.dumps(system_prompt_veloce_website_insights)
            )
        else:
            raw_response = await ai_service.openai_call_conversation_analysis(
                formatted_messages,
                json.dumps(system_prompt_extract_chat_insights)
            )

        try:
            parsed = json.loads(raw_response)
        except json.JSONDecodeError:
            logger.error(
                f"Failed to parse OpenAI response for conversation {conversation__id}: {raw_response}")
            raise

        if tenant_id is "veloce_website":
            saved = await repo.upsert_website_conversation_insights(
                db,
                conversation__id=conversation__id,
                tenant_id=tenant_id,
                insights=parsed.get("insights", {}),
                # updates conversation.lead_* fields
                lead_data=parsed.get("lead"),
            )
            await email_service.send_website_lead_insight_email(insights=parsed.get("insights", {}),
                                                                lead=parsed.get(
                                                                    "lead"),
                                                                messages=formatted_messages,
                                                                recipients=["muhammadhamzakhalid24@gmail.com", "muhammadhamzakhalid248@gmail.com", "khuzaima.ansari@odysseynleo.com.au", "Taha.salman@odysseynleo.com.au"])
        else:
            saved = await repo.upsert_conversation_insights(
                db,
                conversation__id=conversation__id,
                tenant_id=tenant_id,
                insights=parsed.get("insights", {}),
                # updates conversation.lead_* fields
                lead_data=parsed.get("lead"),
            )
            await email_service.send_lead_insight_email(insights=parsed.get("insights", {}),
                                                    lead=parsed.get("lead"),
                                                    messages=formatted_messages,
                                                    recipients=["muhammadhamzakhalid24@gmail.com", "muhammadhamzakhalid248@gmail.com", "khuzaima.ansari@odysseynleo.com.au", "Taha.salman@odysseynleo.com.au"])

        await repo.update_conversation_status(
            db,
            conversation__id=conversation__id,
            tenant_id=tenant_id,
            status=chat_schema.ConversationStatus.emailed.value
        )
        await db.commit()

        return {"insights_id": saved.id, "conversation_id": conversation__id}
