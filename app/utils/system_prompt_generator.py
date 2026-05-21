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
    system_prompt: str | None = None,
    custom_instructions: str | None = None,
) -> str:
    """
    Combine personality + company profile into the static system prompt string.

    Two personality authoring modes:
      - system_prompt (str): plain-text prompt written by an admin. Used as-is.
      - personality_content (dict): structured JSONB (ARIA/LEO style). Rendered
        into prose by _render_personality.
    system_prompt takes precedence when both are provided.

    custom_instructions, if set, are appended at the end as an explicit
    "CUSTOM INSTRUCTIONS" block so the tenant's overrides are always visible
    to the LLM with clear priority.

    Returns a UTF-8 text blob for ChatbotConfig.system_prompt_template.
    """
    parts: list[str] = []

    # ── 1. Personality base ──────────────────────────────────────────────────
    if system_prompt:
        parts.append(system_prompt.strip())
    elif personality_content:
        parts.append(_render_personality(personality_content))

    # ── 2. Company profile (tenant-specific context) ─────────────────────────
    profile_text = _render_company_profile(company_profile)
    if profile_text:
        parts.append("## COMPANY CONTEXT\n" + profile_text)

    # ── 3. Tenant custom instructions override ───────────────────────────────
    if custom_instructions and custom_instructions.strip():
        parts.append(
            "## CUSTOM INSTRUCTIONS\n"
            "The following instructions take priority over any conflicting rules above:\n\n"
            + custom_instructions.strip()
        )

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _render_personality(personality_content: dict[str, Any]) -> str:
    """
    Render personality_content JSON as structured natural-language instructions.

    The ARIA personality JSON has the shape:
        {"SystemPrompt": {"Identity": {...}, "HardRules": [...], ...}}

    We extract the key sections and write them out as explicit, clearly labelled
    prose so the LLM doesn't have to mentally parse nested JSON to find the rules.
    Sections are ordered by behavioural priority: role → hard rules →
    conversation flow → formatting → lead capture → other details.
    """
    sp: dict[str, Any] = personality_content.get("SystemPrompt", personality_content)

    sections: list[str] = []

    # ── Role and identity ────────────────────────────────────────────────────
    identity = sp.get("Identity", {})
    role_lines: list[str] = []
    if identity.get("Role"):
        role_lines.append(identity["Role"])
    if identity.get("ToneRule"):
        role_lines.append(f"Tone: {identity['ToneRule']}")
    if identity.get("VoiceRule"):
        role_lines.append(f"Voice: {identity['VoiceRule']}")
    if identity.get("SelfIntroductionRule"):
        role_lines.append(f"Introduction rule: {identity['SelfIntroductionRule']}")
    if identity.get("GreetingRule"):
        role_lines.append(f"Greeting rule: {identity['GreetingRule']}")
    if role_lines:
        sections.append("## IDENTITY AND ROLE\n" + "\n\n".join(role_lines))

    # ── Hard rules (non-negotiable) — most important, read first ────────────
    hard_rules = sp.get("HardRules", [])
    if hard_rules:
        rules_text = "\n".join(f"{i + 1}. {r}" for i, r in enumerate(hard_rules))
        sections.append(
            "## HARD RULES — FOLLOW WITHOUT EXCEPTION\n"
            "These rules override everything else. Violating any one of them is a failure.\n\n"
            + rules_text
        )

    # ── Conversation philosophy and flow ─────────────────────────────────────
    philosophy = sp.get("ConversationPhilosophy", "")
    if philosophy:
        sections.append(
            "## CONVERSATION FLOW — THIS IS THE REQUIRED ORDER\n"
            + philosophy
            + "\n\nStep 1 is always CONNECTION. Never jump straight to qualification questions "
            "like 'Are you looking to rent or buy?' on the first exchange. "
            "Start with a warm, open question that invites the visitor to share what is on their mind. "
            "Only move to qualification (budget, bedrooms, suburb) once you have established warmth and context."
        )

    # ── Australian language style ────────────────────────────────────────────
    aus = sp.get("AustralianLanguageStyle", {})
    aus_lines: list[str] = []
    if aus.get("Spelling"):
        aus_lines.append(aus["Spelling"])
    if aus.get("ConversationStyle"):
        aus_lines.append(aus["ConversationStyle"])
    banned_phrases = aus.get("BannedAmericanPhrases", [])
    if banned_phrases:
        flat = banned_phrases if isinstance(banned_phrases, str) else " / ".join(
            p if isinstance(p, str) else str(p) for p in banned_phrases
        )
        aus_lines.append(f"Banned American phrases: {flat}")
    if aus_lines:
        sections.append("## AUSTRALIAN LANGUAGE STYLE\n" + "\n".join(aus_lines))

    # ── Formatting rules ─────────────────────────────────────────────────────
    fmt = sp.get("FormattingRules", {})
    fmt_lines: list[str] = []
    for key in ("NoEmojiRule", "NoBulletRule", "NoDashRule", "ResponseLength",
                "ShortInputShortOutput", "NoPadding"):
        val = fmt.get(key)
        if val:
            fmt_lines.append(val)
    if fmt_lines:
        sections.append("## FORMATTING RULES\n" + "\n".join(fmt_lines))

    # ── Lead capture ─────────────────────────────────────────────────────────
    lc = sp.get("LeadCapture", {})
    lc_lines: list[str] = []
    if lc.get("PrimaryGoal"):
        lc_lines.append(lc["PrimaryGoal"])
    order = lc.get("OrderOfCapture", [])
    if order:
        lc_lines.append("Order of capture: " + " → ".join(order if isinstance(order, list) else [order]))
    if lc.get("FramingRule"):
        lc_lines.append(lc["FramingRule"])
    if lc.get("DeclineRule"):
        lc_lines.append(lc["DeclineRule"])
    banned_lc = lc.get("BANNED", [])
    if banned_lc:
        lc_lines.append("Never: " + " / ".join(banned_lc if isinstance(banned_lc, list) else [banned_lc]))
    if lc_lines:
        sections.append("## LEAD CAPTURE\n" + "\n".join(lc_lines))

    # ── Viewing and booking policy ────────────────────────────────────────────
    vbp = sp.get("ViewingAndBookingPolicy", {})
    if vbp.get("CriticalRule"):
        sections.append("## VIEWING AND BOOKING POLICY\n" + vbp["CriticalRule"])

    # ── Time awareness ────────────────────────────────────────────────────────
    ta = sp.get("TimeAwareness", {})
    if ta.get("Rule"):
        sections.append("## TIME AWARENESS\n" + ta["Rule"])

    # ── Fallback: any top-level keys not handled above ────────────────────────
    _handled = {
        "Identity", "HardRules", "ConversationPhilosophy", "AustralianLanguageStyle",
        "FormattingRules", "LeadCapture", "ViewingAndBookingPolicy", "TimeAwareness",
        "Version", "UseCaseName", "DeploymentContext",
    }
    extras: list[str] = []
    for key, val in sp.items():
        if key not in _handled:
            extras.append(f"{key}: {json.dumps(val, ensure_ascii=False)}")
    if extras:
        sections.append("## ADDITIONAL RULES\n" + "\n".join(extras))

    return "\n\n".join(sections)


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
# Campaign overlay builder (called in chat service per request when a campaign
# is matched to the visitor's page URL)
# ---------------------------------------------------------------------------

def build_campaign_overlays_block(campaigns: list) -> str:
    """
    Build LAYER 2 for one or more matched campaigns.

    Single campaign  → same output as the original build_campaign_overlay_block.
    Multiple campaigns → sections separated under a shared header so the LLM
    understands it is serving several concurrent campaign goals.
    """
    if not campaigns:
        return ""
    if len(campaigns) == 1:
        return build_campaign_overlay_block(campaigns[0])

    parts: list[str] = [
        "## CAMPAIGN CONTEXT",
        f"You are operating under {len(campaigns)} active campaigns simultaneously. "
        "Apply all goals and instructions below.",
    ]
    for i, campaign in enumerate(campaigns, 1):
        parts.append(f"\n### Campaign {i}: {campaign.name}")
        if campaign.description:
            parts.append(f"Objective: {campaign.description}")
        if campaign.prompt_overlay:
            parts.append("")
            parts.append(campaign.prompt_overlay)
    return "\n".join(parts)


def build_campaign_overlay_block(campaign) -> str:
    """
    Render a Campaign row as the LAYER 2 system prompt block.

    Injected between:
      LAYER 1  →  static base (personality + company profile)
      LAYER 2  →  THIS (campaign context)       ← here
      LAYER 3  →  dynamic suffix (RAG + time + returning visitor)

    Keeps the LLM aware of the campaign's goal without disrupting the
    base persona or polluting the factual RAG context.
    """
    lines: list[str] = [
        "## CAMPAIGN CONTEXT",
        f"You are currently operating under the '{campaign.name}' campaign.",
    ]
    if campaign.description:
        lines.append(f"Campaign objective: {campaign.description}")
    if campaign.prompt_overlay:
        lines.append("")  # blank line before custom instructions
        lines.append(campaign.prompt_overlay)
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
        # Separate listing chunks (marked with source_type=listing) from KB chunks.
        # Listing chunks start with "**" (the title bold marker from _listing_to_context)
        # or contain "Type: sale/rent" — we use a simple heuristic: any chunk that
        # contains "Status: active" or "Type: sale" or "Type: rent" is a listing.
        listing_chunks = [
            c for c in rag_chunks
            if "Status: active" in c or "Type: sale" in c or "Type: rent" in c
        ]
        kb_chunks = [c for c in rag_chunks if c not in listing_chunks]

        if listing_chunks:
            listing_block = "\n\n---\n\n".join(listing_chunks)
            parts.append(
                "## AVAILABLE PROPERTY LISTINGS\n"
                "The following are REAL, CURRENT listings from the database. "
                "Only reference details that appear here. Do not invent or hallucinate listings.\n\n"
                "LISTING PRESENTATION RULES:\n"
                "1. Never say 'no results found' or 'I don't have any listings'. "
                "If an exact match is not available, present the closest 2-3 options and briefly explain "
                "why they are worth considering (value, location, features).\n"
                "2. When a visitor mentions a budget or bedroom count, if no exact match exists, "
                "suggest the nearest options — typically within 10-20% of their stated budget or "
                "one bedroom above/below — and frame it naturally, not as a push: "
                "'The closest we have at the moment is...' not 'You should upgrade your budget'.\n"
                "3. Always highlight what makes a listing valuable: price per feature, location lifestyle, "
                "standout features (pool, garage, land size). Give the visitor a reason to be interested.\n"
                "4. Present the top 2-3 most relevant options when possible — give the visitor choice.\n"
                "5. When a visitor shows genuine interest in a listing, move the conversation toward "
                "next steps naturally: offer more details or let them know the team can arrange a "
                "walkthrough. Do not push — just open the door.\n"
                "6. Stay in the ARIA tone — warm, Aussie, unhurried. This is guidance, not a hard sell.\n\n"
                + listing_block
            )

        if kb_chunks:
            context_block = "\n\n---\n\n".join(kb_chunks)
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
