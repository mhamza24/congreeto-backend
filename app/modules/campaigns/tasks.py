# app/modules/campaigns/tasks.py
"""
Background Celery task for campaign prompt generation.

  generate_campaign_prompt  — fired after create/update to refine prompt_overlay
                               via an OpenAI call. Returns immediately; the field
                               is written back once the LLM responds.
"""
from __future__ import annotations

import asyncio
import logging

from app.config.celery_worker import celery_app, QUEUEEnum
from app.config.settings import get_settings
from app.core.database import get_task_db_session
from app.modules.open_ai import service as ai_service

logger = logging.getLogger(__name__)
settings = get_settings()

# ---------------------------------------------------------------------------
# System instructions sent to the LLM
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert AI prompt engineer specialising in real-estate chatbot campaigns.
Your job is to write a concise, high-impact CAMPAIGN INSTRUCTION BLOCK that will be
injected into a chatbot's system prompt at runtime whenever a visitor lands on the
pages this campaign targets.

Rules:
- Output ONLY the instruction block — no preamble, no markdown fences, no explanations.
- Write in second person, addressing the AI assistant directly ("You are on the...").
- Keep it under 300 words.
- Be specific: state the visitor context, the campaign goal, and 1–3 concrete
  behavioural directions the AI should follow on this page.
- Tone must match a warm, professional real-estate assistant.
- End with a single clear call-to-action the AI should drive toward.
"""


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------

@celery_app.task(
    bind=True,
    name="app.modules.campaigns.tasks.generate_campaign_prompt",
    max_retries=3,
    default_retry_delay=10,
    queue=QUEUEEnum.ANALYSIS.value,
)
def generate_campaign_prompt(self, campaign_public_id: str, tenant_id: int):
    """
    Use OpenAI to generate / refine the campaign's prompt_overlay.
    Writes the result back to the DB row.  Never overwrites a user-edited
    value that was set *after* this task was enqueued — the fetch inside
    _run() reads the live row, so a concurrent save will simply be the
    base for the LLM to improve on.
    """
    logger.info(
        "[campaign] generate_campaign_prompt started campaign=%s tenant=%s",
        campaign_public_id, tenant_id,
    )

    async def _run() -> None:
        from app.modules.campaigns import repository as repo

        async with get_task_db_session() as db:
            campaign = await repo.get_campaign_by_public_id(
                db, tenant_id=tenant_id, public_id=campaign_public_id
            )
            if campaign is None:
                logger.warning(
                    "[campaign] generate_campaign_prompt: campaign not found campaign=%s",
                    campaign_public_id,
                )
                return

            # ── Build the user message ────────────────────────────────────────
            url_hint = (
                f"URL patterns that trigger this campaign: {', '.join(campaign.url_patterns)}"
                if campaign.url_patterns
                else "This is the default catch-all campaign (no specific URL targeting)."
            )
            draft_hint = (
                f"\n\nThe user has provided these draft instructions as a starting point "
                f"— improve them:\n{campaign.prompt_overlay}"
                if campaign.prompt_overlay
                else ""
            )

            user_message = (
                f"Campaign name: {campaign.name}\n"
                f"Description: {campaign.description or 'Not provided.'}\n"
                f"{url_hint}"
                f"{draft_hint}\n\n"
                "Write the campaign instruction block now."
            )

            # ── Call OpenAI ───────────────────────────────────────────────────
            generated, _ = await ai_service.openai_call_with_usage(
                messages=[{"role": "user", "content": user_message}],
                system_instructions=_SYSTEM_PROMPT,
            )

            if not generated or generated.startswith("Sorry,"):
                logger.warning(
                    "[campaign] generate_campaign_prompt: LLM returned empty/error "
                    "response campaign=%s — skipping write",
                    campaign_public_id,
                )
                return

            # ── Persist ───────────────────────────────────────────────────────
            campaign.prompt_overlay = generated[:4000]  # enforce DB column max
            await db.commit()
            logger.info(
                "[campaign] generate_campaign_prompt: prompt_overlay updated campaign=%s",
                campaign_public_id,
            )

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_run())
        finally:
            loop.close()
            asyncio.set_event_loop(None)
    except Exception as exc:
        countdown = min(300, 2 ** self.request.retries * 10)
        logger.warning(
            "[campaign] generate_campaign_prompt failed campaign=%s retry_in=%ds error=%s",
            campaign_public_id, countdown, exc,
        )
        raise self.retry(exc=exc, countdown=countdown)
