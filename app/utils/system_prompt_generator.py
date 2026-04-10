"""
system_prompt_generator.py

Assembles the STATIC portion of the chatbot system prompt from:
  1. A PromptPersonality's personality_content JSON (ARIA, LEO, etc.)
  2. The chatbot's company_profile JSON (company name, website, vision, etc.)

The static portion is saved to ChatbotConfig.system_prompt_template and
regenerated whenever the chatbot config or company_profile is updated.

At chat time, dynamic parts are appended on top of this static base:
  - RAG knowledge-base context (retrieved per user query)
  - Time awareness (user's local timestamp)
  - Returning-visitor recap (if applicable)

This separation means the LLM always gets a consistent, pre-built persona
without re-serialising the full personality JSON on every request.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_static_system_prompt(
    personality_content: dict[str, Any],
    company_profile: dict[str, Any],
) -> str:
    """
    Combine personality + company profile into the static system prompt string.

    Returns a UTF-8 text blob suitable for storage in
    ChatbotConfig.system_prompt_template.
    """
    parts: list[str] = []

    # ── 1. Personality (ARIA rules, tone, QA pairs, etc.) ────────────────────
    if personality_content:
        parts.append(
            "## PERSONALITY AND BEHAVIOUR RULES\n"
            + json.dumps(personality_content, ensure_ascii=False)
        )

    # ── 2. Company profile (tenant-specific context) ──────────────────────────
    profile_text = _render_company_profile(company_profile)
    if profile_text:
        parts.append("## COMPANY CONTEXT\n" + profile_text)

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PROFILE_KEYS = [
    ("company_name",        "Company Name"),
    ("tagline",             "Tagline"),
    ("company_description", "Description"),
    ("company_vision",      "Vision"),
    ("company_website",     "Website"),
    ("contact_email",       "Contact Email"),
    ("contact_phone",       "Contact Phone"),
    ("locations",           "Locations"),
    ("portfolio_summary",   "Portfolio Summary"),
    ("industry",            "Industry"),
]


def _render_company_profile(profile: dict[str, Any]) -> str:
    """
    Render the company_profile dict as a structured plain-text block.

    Returns an empty string if the profile is empty or all values are falsy,
    so no stale placeholder ends up in the prompt.
    """
    if not profile:
        return ""

    lines: list[str] = []
    for key, label in _PROFILE_KEYS:
        value = profile.get(key)
        if not value:
            continue
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value if v)
        if value:
            lines.append(f"{label}: {value}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Runtime dynamic-parts builder (called in chat service per request)
# ---------------------------------------------------------------------------

def build_dynamic_context(
    *,
    rag_chunks: list[str] | None = None,
    time_prompt: dict | None = None,
    returning_visitor_prompt: dict | None = None,
) -> str:
    """
    Build the dynamic suffix appended to the static system prompt at chat time.

    Parameters
    ----------
    rag_chunks:
        List of raw chunk content strings from the hybrid RAG search.
    time_prompt:
        Dict from get_time_awareness_prompt().
    returning_visitor_prompt:
        Dict from get_returning_visitor_prompt().

    Returns
    -------
    A string to concatenate after the static system_prompt_template.
    Empty string if no dynamic context is available.
    """
    parts: list[str] = []

    # ── RAG knowledge context ────────────────────────────────────────────────
    if rag_chunks:
        context_block = "\n\n---\n\n".join(rag_chunks)
        parts.append(
            "## RELEVANT KNOWLEDGE BASE CONTEXT\n"
            "Use the information below to answer the visitor's question. "
            "Only reference details that are directly relevant. "
            "Do not invent information not present here.\n\n"
            + context_block
        )

    # ── Time awareness ───────────────────────────────────────────────────────
    if time_prompt:
        parts.append("## TIME AWARENESS\n" + json.dumps(time_prompt, ensure_ascii=False))

    # ── Returning visitor recap ───────────────────────────────────────────────
    if returning_visitor_prompt:
        parts.append(
            "## IMMEDIATE ACTION — RETURNING VISITOR\n"
            "EXECUTE BEFORE ANYTHING ELSE: acknowledge the visitor's return and "
            "give a natural recap of your previous conversation. Context:\n"
            + json.dumps(returning_visitor_prompt, ensure_ascii=False)
        )

    return "\n\n".join(parts)
