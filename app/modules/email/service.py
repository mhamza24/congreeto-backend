from __future__ import annotations
from typing import Any

from fastapi_mail import FastMail, MessageSchema, MessageType
from app.config.email import conf as email_config
from app.config.settings import get_settings

settings = get_settings()
import logging

logger = logging.getLogger(__name__)
fm = FastMail(email_config)


print(f"Using server: {settings.MAIL_SERVER}")
print(f"Using port: {settings.MAIL_PORT}")
print(f"Using username: {settings.MAIL_USERNAME}")


async def test(recipients_list: list[str], username: str = "MHK"):
    message = MessageSchema(
        subject="Welcome to Our App!",
        recipients=recipients_list,
        body=f"<h1>Welcome, {username}!</h1><p>Thanks for signing up.</p>",
        subtype=MessageType.html
    )
    await fm.send_message(message)


# ──────────────────────────────────────────────────────────────
# Shared helpers (used by both property + website emails)
# ──────────────────────────────────────────────────────────────

TIER_ACCENT = {
    "hot":     "#D93025",
    "warm":    "#E8780C",
    "nurture": "#0F7B6C",
    "cold":    "#3A5F8A",
}


def _fmt_currency(value: int | None, currency: str = "AUD") -> str | None:
    if value is None:
        return None
    if value >= 1_000_000:
        return f"{currency} {value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"{currency} {value / 1_000:.0f}K"
    return f"{currency} {value:,}"


def _budget_line(ins: dict) -> str | None:
    lo  = ins.get("budget_min")
    hi  = ins.get("budget_max")
    cur = ins.get("budget_currency") or "AUD"
    if lo and hi:
        return f"{_fmt_currency(lo, cur)} – {_fmt_currency(hi, cur)}"
    if lo:
        return f"From {_fmt_currency(lo, cur)}"
    if hi:
        return f"Up to {_fmt_currency(hi, cur)}"
    return None


def _render_messages(messages: list[dict]) -> str:
    rows = []
    for m in messages:
        role    = (m.get("role") or "").lower()
        content = m.get("content", "")
        is_lead = role in ("user", "lead", "customer")
        label   = "Visitor" if is_lead else "ARIA"
        align   = "left" if is_lead else "right"
        bg      = "#F4F6F9" if is_lead else "#FFFFFF"
        border  = "#D8DDE6" if is_lead else "#EAEDF0"

        rows.append(f"""
        <tr>
          <td style="padding:4px 0;text-align:{align};">
            <div style="display:inline-block;max-width:82%;text-align:left;">
              <div style="font-size:10px;color:#9AA5B4;font-weight:600;
                          text-transform:uppercase;letter-spacing:.8px;margin-bottom:3px;">
                {label}
              </div>
              <div style="background:{bg};border:1px solid {border};
                          border-radius:8px;padding:9px 13px;
                          font-size:13px;color:#2D3748;line-height:1.55;">
                {content}
              </div>
            </div>
          </td>
        </tr>""")
    return "\n".join(rows)


def _kv(label: str, value: str | None) -> str:
    """Renders a key-value row. Returns empty string if value is falsy."""
    if not value:
        return ""
    return f"""
    <tr>
      <td style="padding:5px 0;font-size:12px;color:#718096;
                 width:30%;vertical-align:top;">{label}</td>
      <td style="padding:5px 0;font-size:13px;color:#1A202C;font-weight:500;">{value}</td>
    </tr>"""


def _pill_list(items: list[str] | None, accent: str) -> str | None:
    """
    Renders a list of strings as inline pill badges.
    Used for pain points, topics, business location etc.
    Returns None if items is empty or None.
    """
    if not items:
        return None
    pills = "".join(
        f'<span style="display:inline-block;margin:2px 3px 2px 0;padding:2px 9px;'
        f'border-radius:12px;background:#F4F6F9;border:1px solid #D8DDE6;'
        f'font-size:11px;color:#2D3748;">{item}</span>'
        for item in items
    )
    return f'<div style="line-height:2;">{pills}</div>'


# ──────────────────────────────────────────────────────────────
# Property lead email (original)
# ──────────────────────────────────────────────────────────────

def build_lead_email_html(
    lead: dict,
    insights: dict,
    messages: list[dict],
) -> str:
    tier   = (insights.get("lead_tier") or "cold").lower()
    accent = TIER_ACCENT.get(tier, "#3A5F8A")

    lead_name  = lead.get("name")
    lead_email = lead.get("email")
    lead_phone = lead.get("phone")
    has_contact = any([lead_name, lead_email, lead_phone])

    contact_rows = (
        _kv("Name",  lead_name)  +
        _kv("Email", lead_email) +
        _kv("Phone", lead_phone)
    )

    tier_badge = (
        f'<span style="display:inline-block;padding:2px 10px;border-radius:4px;'
        f'background:{accent};color:#fff;font-size:11px;font-weight:700;'
        f'letter-spacing:.8px;text-transform:uppercase;">{tier.upper()}</span>'
    )
    score  = insights.get("lead_score")
    intent = (insights.get("intent") or "").title() or None
    budget = _budget_line(insights)

    overview_rows = (
        _kv("Lead Tier", tier_badge) +
        _kv("Score",     f"{score}/100" if score is not None else None) +
        _kv("Intent",    intent) +
        _kv("Budget",    budget)
    )

    ai_summary  = insights.get("ai_summary")  or "No summary available."
    ai_insights = insights.get("ai_insights") or "No insights available."
    message_rows = _render_messages(messages)

    contact_block = f"""
    <tr><td style="padding:20px 36px 0;">
      <div style="font-size:10px;font-weight:700;letter-spacing:1.5px;
                  text-transform:uppercase;color:#9AA5B4;margin-bottom:10px;">
        Contact
      </div>
      <table width="100%" cellpadding="0" cellspacing="0">{contact_rows}</table>
    </td></tr>
    <tr><td style="padding:16px 36px 0;">
      <hr style="border:none;border-top:1px solid #EAEDF0;margin:0;"/>
    </td></tr>""" if has_contact else ""

    return _render_email_shell(
        accent=accent,
        header_label="New Property Lead",
        lead_name=lead_name,
        contact_block=contact_block,
        overview_rows=overview_rows,
        ai_summary=ai_summary,
        ai_insights=ai_insights,
        message_rows=message_rows,
        recommended_action=insights.get("recommended_action"),
    )


# ──────────────────────────────────────────────────────────────
# Website (B2B) lead email — new
# ──────────────────────────────────────────────────────────────

def build_website_lead_email_html(
    lead: dict,
    insights: dict,
    messages: list[dict],
) -> str:
    """
    Build the lead notification email for Veloce WEBSITE (B2B) conversations.

    Column remapping applied here mirrors upsert_website_conversation_insights:
      budget_currency   → subscription preference
      suburbs_mentioned → pain points
      cities_mentioned  → business operating locations
      property_types    → business type (single-item array)
      budget_min/max    → always None (not rendered)
      bedrooms_wanted   → always None (not rendered)
    """
    tier   = (insights.get("lead_tier") or "cold").lower()
    accent = TIER_ACCENT.get(tier, "#3A5F8A")

    # ── Contact ──────────────────────────────────────────────
    lead_name  = lead.get("name")
    lead_email = lead.get("email")
    lead_phone = lead.get("phone")
    has_contact = any([lead_name, lead_email, lead_phone])

    contact_rows = (
        _kv("Name",  lead_name)  +
        _kv("Email", lead_email) +
        _kv("Phone", lead_phone)
    )

    # ── Overview — B2B fields ────────────────────────────────
    tier_badge = (
        f'<span style="display:inline-block;padding:2px 10px;border-radius:4px;'
        f'background:{accent};color:#fff;font-size:11px;font-weight:700;'
        f'letter-spacing:.8px;text-transform:uppercase;">{tier.upper()}</span>'
    )

    score = insights.get("lead_score")

    # intent comes through as-is (e.g. "demo_request") — prettify for display
    raw_intent = insights.get("intent") or ""
    intent_display = raw_intent.replace("_", " ").title() or None

    # business type: stored as single-item array in property_types
    business_type_arr = insights.get("property_types")
    business_type = (
        business_type_arr[0].replace("_", " ").title()
        if business_type_arr else None
    )

    # business location: stored as array in cities_mentioned
    business_location_arr = insights.get("cities_mentioned")
    business_location = (
        ", ".join(business_location_arr)
        if business_location_arr else None
    )

    # subscription preference: stored in budget_currency
    sub_pref = (insights.get("budget_currency") or "").title() or None

    timeline = (insights.get("timeline") or "").replace("_", " ").title() or None

    overview_rows = (
        _kv("Lead Tier",     tier_badge) +
        _kv("Score",         f"{score}/100" if score is not None else None) +
        _kv("Intent",        intent_display) +
        _kv("Business Type", business_type) +
        _kv("Location",      business_location) +
        _kv("Subscription",  sub_pref) +
        _kv("Timeline",      timeline)
    )

    # ── Pain Points — stored in suburbs_mentioned ────────────
    pain_points     = insights.get("suburbs_mentioned")
    pain_points_html = _pill_list(pain_points, accent)

    pain_points_block = f"""
    <tr><td style="padding:16px 36px 0;">
      <hr style="border:none;border-top:1px solid #EAEDF0;margin:0;"/>
    </td></tr>
    <tr><td style="padding:20px 36px 0;">
      <div style="font-size:10px;font-weight:700;letter-spacing:1.5px;
                  text-transform:uppercase;color:#9AA5B4;margin-bottom:10px;">
        Pain Points
      </div>
      {pain_points_html}
    </td></tr>""" if pain_points_html else ""

    # ── Topics ───────────────────────────────────────────────
    topics      = insights.get("topics_mentioned")
    topics_html = _pill_list(topics, accent)

    topics_block = f"""
    <tr><td style="padding:16px 36px 0;">
      <hr style="border:none;border-top:1px solid #EAEDF0;margin:0;"/>
    </td></tr>
    <tr><td style="padding:20px 36px 0;">
      <div style="font-size:10px;font-weight:700;letter-spacing:1.5px;
                  text-transform:uppercase;color:#9AA5B4;margin-bottom:10px;">
        Topics Discussed
      </div>
      {topics_html}
    </td></tr>""" if topics_html else ""

    # ── Contact block ────────────────────────────────────────
    contact_block = f"""
    <tr><td style="padding:20px 36px 0;">
      <div style="font-size:10px;font-weight:700;letter-spacing:1.5px;
                  text-transform:uppercase;color:#9AA5B4;margin-bottom:10px;">
        Contact
      </div>
      <table width="100%" cellpadding="0" cellspacing="0">{contact_rows}</table>
    </td></tr>
    <tr><td style="padding:16px 36px 0;">
      <hr style="border:none;border-top:1px solid #EAEDF0;margin:0;"/>
    </td></tr>""" if has_contact else ""

    ai_summary   = insights.get("ai_summary")  or "No summary available."
    ai_insights  = insights.get("ai_insights") or "No insights available."
    message_rows = _render_messages(messages)

    return _render_email_shell(
        accent=accent,
        header_label="New Website Enquiry",
        lead_name=lead_name,
        contact_block=contact_block,
        overview_rows=overview_rows,
        ai_summary=ai_summary,
        ai_insights=ai_insights,
        message_rows=message_rows,
        recommended_action=insights.get("recommended_action"),
        extra_blocks=pain_points_block + topics_block,
    )


# ──────────────────────────────────────────────────────────────
# Shared HTML shell (used by both builders)
# ──────────────────────────────────────────────────────────────

def _render_email_shell(
    *,
    accent: str,
    header_label: str,
    lead_name: str | None,
    contact_block: str,
    overview_rows: str,
    ai_summary: str,
    ai_insights: str,
    message_rows: str,
    recommended_action: str | None = None,
    extra_blocks: str = "",
) -> str:
    recommended_block = f"""
    <tr><td style="padding:16px 36px 0;">
      <hr style="border:none;border-top:1px solid #EAEDF0;margin:0;"/>
    </td></tr>
    <tr><td style="padding:20px 36px 0;">
      <div style="font-size:10px;font-weight:700;letter-spacing:1.5px;
                  text-transform:uppercase;color:#9AA5B4;margin-bottom:10px;">
        Recommended Action
      </div>
      <div style="font-size:13px;color:#FFFFFF;line-height:1.65;
                  background:{accent};border-radius:8px;padding:12px 16px;
                  font-weight:500;">
        {recommended_action}
      </div>
    </td></tr>""" if recommended_action else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>New Lead</title>
</head>
<body style="margin:0;padding:0;background:#F2F4F7;
             font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;">

<table width="100%" cellpadding="0" cellspacing="0"
       style="background:#F2F4F7;padding:36px 16px;">
  <tr><td align="center">
  <table width="580" cellpadding="0" cellspacing="0"
         style="max-width:580px;background:#FFFFFF;border-radius:10px;
                overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,.07);">

    <!-- Accent bar -->
    <tr>
      <td style="background:{accent};height:4px;font-size:0;line-height:0;">&nbsp;</td>
    </tr>

    <!-- Header -->
    <tr>
      <td style="padding:28px 36px 20px;">
        <div style="font-size:11px;color:#9AA5B4;letter-spacing:1.5px;
                    text-transform:uppercase;margin-bottom:6px;">
          {header_label}
        </div>
        <div style="font-size:22px;font-weight:700;color:#1A202C;">
          {lead_name or "Unknown Visitor"}
        </div>
      </td>
    </tr>

    <tr><td style="padding:0 36px;">
      <hr style="border:none;border-top:1px solid #EAEDF0;margin:0;"/>
    </td></tr>

    {contact_block}

    <!-- Overview -->
    <tr><td style="padding:20px 36px 0;">
      <div style="font-size:10px;font-weight:700;letter-spacing:1.5px;
                  text-transform:uppercase;color:#9AA5B4;margin-bottom:10px;">
        Overview
      </div>
      <table width="100%" cellpadding="0" cellspacing="0">{overview_rows}</table>
    </td></tr>

    {extra_blocks}

    <tr><td style="padding:16px 36px 0;">
      <hr style="border:none;border-top:1px solid #EAEDF0;margin:0;"/>
    </td></tr>

    <!-- Summary -->
    <tr><td style="padding:20px 36px 0;">
      <div style="font-size:10px;font-weight:700;letter-spacing:1.5px;
                  text-transform:uppercase;color:#9AA5B4;margin-bottom:10px;">
        Summary
      </div>
      <div style="font-size:13px;color:#2D3748;line-height:1.75;
                  border-left:3px solid {accent};padding-left:14px;">
        {ai_summary}
      </div>
    </td></tr>

    <!-- Insights -->
    <tr><td style="padding:20px 36px 0;">
      <div style="font-size:10px;font-weight:700;letter-spacing:1.5px;
                  text-transform:uppercase;color:#9AA5B4;margin-bottom:10px;">
        Insights
      </div>
      <div style="font-size:13px;color:#2D3748;line-height:1.75;
                  border-left:3px solid #CBD5E0;padding-left:14px;">
        {ai_insights}
      </div>
    </td></tr>

    {recommended_block}

    <tr><td style="padding:20px 36px 0;">
      <hr style="border:none;border-top:1px solid #EAEDF0;margin:0;"/>
    </td></tr>

    <!-- Transcript -->
    <tr><td style="padding:20px 36px 0;">
      <div style="font-size:10px;font-weight:700;letter-spacing:1.5px;
                  text-transform:uppercase;color:#9AA5B4;margin-bottom:14px;">
        Conversation
      </div>
      <table width="100%" cellpadding="0" cellspacing="0">
        {message_rows}
      </table>
    </td></tr>

    <!-- Footer -->
    <tr>
      <td style="padding:28px 36px;text-align:center;font-size:11px;color:#B0BAC9;">
        Auto-generated by Veloce. Do not reply to this email.
      </td>
    </tr>

  </table>
  </td></tr>
</table>

</body>
</html>"""


# ──────────────────────────────────────────────────────────────
# Public entry points
# ──────────────────────────────────────────────────────────────

async def send_lead_insight_email(
    *,
    insights: dict[str, Any],
    lead: dict[str, Any],
    messages: list[dict],
    recipients: list[str],
) -> None:
    """
    Build and send the lead-insight email for PROPERTY chatbot conversations.
    """
    tier      = (insights.get("lead_tier") or "lead").upper()
    lead_name = lead.get("name") or "New Lead"
    subject   = f"[{tier}] New Lead: {lead_name}"

    html_body = build_lead_email_html(
        lead=lead,
        insights=insights,
        messages=messages,
    )

    await fm.send_message(MessageSchema(
        subject=subject,
        recipients=recipients,
        body=html_body,
        subtype=MessageType.html,
    ))
    logger.info(
        f"Sent lead email to {recipients} for lead {lead_name} with tier {tier}")


async def send_website_lead_insight_email(
    *,
    insights: dict[str, Any],
    lead: dict[str, Any],
    messages: list[dict],
    recipients: list[str],
) -> None:
    """
    Build and send the lead-insight email for WEBSITE (B2B) conversations.

    Displays business type, location, subscription preference, pain points,
    and topics discussed instead of property-specific fields.
    """
    tier      = (insights.get("lead_tier") or "lead").upper()
    lead_name = lead.get("name") or "New Visitor"

    # Prettify intent for subject line: "demo_request" → "Demo Request"
    raw_intent = (insights.get("intent") or "").replace("_", " ").title()
    subject = f"[{tier}] Website Enquiry: {lead_name}"
    if raw_intent:
        subject = f"[{tier}] {raw_intent} — {lead_name}"

    html_body = build_website_lead_email_html(
        lead=lead,
        insights=insights,
        messages=messages,
    )

    await fm.send_message(MessageSchema(
        subject=subject,
        recipients=recipients,
        body=html_body,
        subtype=MessageType.html,
    ))
    logger.info(
        f"Sent website lead email to {recipients} for lead {lead_name} with intent {raw_intent}")
