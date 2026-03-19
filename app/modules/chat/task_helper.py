from app.core.database import get_db, get_task_db_session
import asyncio
import json
from datetime import datetime, timezone, timedelta
from app.utils.system_prompt_chat_analysis import system_prompt_extract_chat_insights, system_prompt_veloce_website_insights
from app.config.settings import get_settings
from app.modules.open_ai import service as ai_service
from app.modules.chat import schemas as chat_schema
from app.modules.email import service as email_service
import logging
from . import repository as repo
import logging

settings = get_settings()
logger = logging.getLogger(__name__)

IDLE_THRESHOLD_MINUTES = settings.CHAT_IDLE_THRESHOLD_MINUTES
CHAT_IDLE_BATCH_SIZE = settings.CHAT_IDLE_BATCH_SIZE


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
        if tenant_id == "veloce_website":
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

        if tenant_id == "veloce_website":
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
                                                                recipients=["muhammadhamzakhalid24@gmail.com", "muhammadhamzakhalid248@gmail.com", "khuzaima.ansari@odysseynleo.com.au"])
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
                                                    recipients=["muhammadhamzakhalid24@gmail.com", "muhammadhamzakhalid248@gmail.com", "khuzaima.ansari@odysseynleo.com.au"])

        # Send follow-up email if lead exists and email is provided
        if parsed.get("email"):
            print(f"email {parsed.get("email")}")
            await email_service.send_conversation_followup_email(
                lead_email=parsed["email"],
                lead_name=parsed.get("name"),
                topics=parsed.get("topics_mentioned") or [
                ],  # website chatbot
                # topics=insights.get("suburbs_mentioned") or [], # property chatbot (pain points)
                messages=messages,
                ai_summary=parsed.get("ai_summary") or "",
            )

        await repo.update_conversation_status(
            db,
            conversation__id=conversation__id,
            tenant_id=tenant_id,
            status=chat_schema.ConversationStatus.emailed.value
        )
        await db.commit()

        return {"insights_id": saved.id, "conversation_id": conversation__id}


async def _fetch_idle_conversations() -> list[tuple[int, str]]:
    """
    Open a short-lived DB session, query idle conversations, close session.
    Isolated here so the Celery task body stays clean and synchronous.
    """
    idle_before = datetime.now(timezone.utc) - \
        timedelta(minutes=IDLE_THRESHOLD_MINUTES)

    async for db in get_db():
        try:
            rows = await repo.get_idle_conversations(db, idle_before=idle_before)
            return [(row.id, row.tenant_id) for row in rows]
        finally:
            await db.close()

    return []


