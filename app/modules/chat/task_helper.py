from app.core.database import get_db, get_task_db_session
import asyncio
import json
from datetime import datetime, timezone, timedelta
from app.utils.system_prompt_chat_analysis import (
    system_prompt_extract_chat_insights,
    system_prompt_veloce_website_insights,
    system_prompt_odysseynleo_website_insights,
    system_prompt_generic_insights,
)
from app.config.settings import get_settings
from app.modules.open_ai import service as ai_service
from app.modules.chat import schemas as chat_schema
from app.modules.email import service as email_service
import logging
from . import repository as repo
from sqlalchemy import text

settings = get_settings()
logger = logging.getLogger(__name__)

# Veloce-owned tenant slugs — lead emails for these go to Veloce internal only
_VELOCE_TENANTS = {"veloce_website", "website_odysseynleo"}

# Fallback recipients when no tenant admin emails are found
_VELOCE_FALLBACK: list[str] = [
    e.strip() for e in settings.INQUIRY_RECIPIENTS.split(",") if e.strip()
]


async def _get_tenant_notification_emails(db, tenant_slug: str) -> list[str]:
    """
    Returns the notification recipients for a tenant chatbot lead email.

    Priority:
      1. tenant.settings->>'notification_email'  (single override)
      2. All active owner + admin + agent emails from tenant_users JOIN users
      3. Veloce fallback (INQUIRY_RECIPIENTS setting)

    The tenant_id stored in conversations is the tenant slug, which maps to
    tenants.slug.
    """
    result = await db.execute(
        text("""
            SELECT
                t.settings->>'notification_email'          AS override_email,
                ARRAY_AGG(u.email ORDER BY
                    CASE tu.role WHEN 'owner' THEN 0
                                 WHEN 'admin' THEN 1
                                 ELSE 2 END
                ) FILTER (WHERE u.email IS NOT NULL)       AS member_emails
            FROM tenants t
            LEFT JOIN tenant_users tu
                   ON tu.tenant_id = t.id
                  AND tu.status    = 'active'
                  AND tu.role      IN ('owner', 'admin', 'agent')
            LEFT JOIN users u
                   ON u.id         = tu.user_id
                  AND u.deleted_at IS NULL
            WHERE t.slug       = :slug
              AND t.deleted_at IS NULL
            GROUP BY t.id, t.settings
        """),
        {"slug": tenant_slug},
    )
    row = result.mappings().first()
    if row is None:
        logger.warning("[task_helper] tenant not found for slug=%s, using fallback", tenant_slug)
        return _VELOCE_FALLBACK

    override = row.get("override_email")
    if override:
        return [override]

    member_emails: list[str] = row.get("member_emails") or []
    if member_emails:
        return member_emails

    logger.warning("[task_helper] no active members for slug=%s, using fallback", tenant_slug)
    return _VELOCE_FALLBACK


async def _get_chatbot_industry(db, tenant_slug: str) -> str:
    """Return the industry slug of the tenant's active chatbot. Defaults to 'generic'."""
    result = await db.execute(
        text("""
            SELECT cc.industry
            FROM chatbot_configs cc
            JOIN tenants t ON t.id = cc.tenant_id
            WHERE t.slug = :slug
              AND cc.status = 'active'
              AND t.deleted_at IS NULL
            LIMIT 1
        """),
        {"slug": tenant_slug},
    )
    row = result.mappings().first()
    return (row.get("industry") or "generic") if row else "generic"


async def _get_company_profile(db, tenant_slug: str) -> dict:
    """
    Returns the company_profile JSONB from the tenant's active chatbot config.
    Falls back to an empty dict if none found.
    """
    result = await db.execute(
        text("""
            SELECT cc.company_profile, cc.branding
            FROM chatbot_configs cc
            JOIN tenants t ON t.id = cc.tenant_id
            WHERE t.slug = :slug
              AND cc.status = 'active'
              AND t.deleted_at IS NULL
            LIMIT 1
        """),
        {"slug": tenant_slug},
    )
    row = result.mappings().first()
    if row is None:
        return {}
    profile: dict = row.get("company_profile") or {}
    branding: dict = row.get("branding") or {}
    # merge logo_url from branding into profile for convenience
    if not profile.get("logo_url") and branding.get("logo_url"):
        profile["logo_url"] = branding["logo_url"]
    return profile

IDLE_THRESHOLD_MINUTES = settings.CHAT_IDLE_THRESHOLD_MINUTES
CHAT_IDLE_BATCH_SIZE = settings.CHAT_IDLE_BATCH_SIZE


async def run_analysis(conversation__id: int, tenant_id: str) -> dict:
    logger.info("[chat] run_analysis started conversation_id=%s tenant=%s", conversation__id, tenant_id)
    async with get_task_db_session() as db:
        chatbot_name = "ARIA"  # default name if not extracted from insights
        messages = await repo.get_conversation_history(
            db,
            conversation__id=conversation__id,
        )
        logger.debug("[chat] run_analysis fetched %d messages conversation_id=%s", len(messages), conversation__id)

        formatted_messages = [
            {"role": msg.role.value, "content": msg.content}
            for msg in messages
        ]
        if tenant_id == "veloce_website":
            analysis_prompt = system_prompt_veloce_website_insights
        elif tenant_id == "website_odysseynleo":
            analysis_prompt = system_prompt_odysseynleo_website_insights
        else:
            industry = await _get_chatbot_industry(db, tenant_id)
            if industry == "real_estate":
                analysis_prompt = system_prompt_extract_chat_insights
            else:
                analysis_prompt = system_prompt_generic_insights

        raw_response = await ai_service.openai_call_conversation_analysis(
            formatted_messages,
            json.dumps(analysis_prompt),
        )

        logger.debug("[chat] run_analysis LLM response received conversation_id=%s", conversation__id)
        try:
            parsed = json.loads(raw_response)
            insights = parsed.get("insights") or {}

            if not isinstance(insights, dict):
                raise ValueError("Expected 'insights' to be a dict")

            chatbot_name = insights.get("chatbot_identity", "ARIA")
        except json.JSONDecodeError:
            logger.error(
                "[chat] run_analysis failed to parse LLM response conversation_id=%s raw=%s",
                conversation__id, raw_response[:200])
            raise

        # Resolve recipients and company branding from DB
        if tenant_id in _VELOCE_TENANTS:
            recipients = _VELOCE_FALLBACK
            company_profile = {}
        else:
            recipients, company_profile = await asyncio.gather(
                _get_tenant_notification_emails(db, tenant_id),
                _get_company_profile(db, tenant_id),
            )

        if tenant_id == "veloce_website":
            saved = await repo.upsert_website_conversation_insights(
                db,
                conversation__id=conversation__id,
                tenant_id=tenant_id,
                insights=insights,
                lead_data=parsed.get("lead"),
            )
            await email_service.send_website_lead_insight_email(
                insights=insights,
                lead=parsed.get("lead"),
                messages=formatted_messages,
                chatbot_name=chatbot_name,
                recipients=recipients,
            )
        else:
            saved = await repo.upsert_conversation_insights(
                db,
                conversation__id=conversation__id,
                tenant_id=tenant_id,
                insights=insights,
                lead_data=parsed.get("lead"),
            )
            await email_service.send_lead_insight_email(
                insights=insights,
                lead=parsed.get("lead"),
                messages=formatted_messages,
                chatbot_name=chatbot_name,
                recipients=recipients,
                company_profile=company_profile,
            )

        # Send follow-up email if lead exists and email is provided
        # Send follow-up email if lead email was captured
        lead = parsed.get("lead") or {}
        insights = parsed.get("insights", {})
        lead_email = lead.get("email")

        if lead_email:
            # website chatbot
            topics = insights.get("topics_mentioned") or [
            ] if tenant_id == "veloce_website" else insights.get("suburbs_mentioned") or []
            # topics   = insights.get("suburbs_mentioned") or []  # property chatbot
            ai_summary = insights.get("ai_summary") or ""

            await email_service.send_conversation_followup_email(
                lead_email=lead_email,
                lead_name=lead.get("name"),
                topics=topics,
                messages=formatted_messages,   # ← formatted, not raw ORM
                ai_summary=ai_summary,
                chatbot_name=chatbot_name,
            )

        await repo.update_conversation_status(
            db,
            conversation__id=conversation__id,
            tenant_id=tenant_id,
            status=chat_schema.ConversationStatus.emailed.value
        )
        await db.commit()

        logger.info("[chat] run_analysis complete conversation_id=%s insights_id=%s", conversation__id, saved.id)
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


