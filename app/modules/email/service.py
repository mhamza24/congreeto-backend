from __future__ import annotations
from typing import Any

from fastapi_mail import FastMail, MessageSchema, MessageType
from app.config.email import conf as email_config

fm = FastMail(email_config)


async def test(recipients_list: list[str], username: str = "MHK"):
    message = MessageSchema(
        subject="Welcome to Our App!",
        recipients=recipients_list,
        body=f"<h1>Welcome, {username}!</h1><p>Thanks for signing up.</p>",
        subtype=MessageType.html
    )
    await fm.send_message(message)


# ──────────────────────────────────────────────────────────────
# Helpers
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
        label   = "Lead" if is_lead else "Agent"
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


# ──────────────────────────────────────────────────────────────
# HTML builder
# ──────────────────────────────────────────────────────────────

def build_lead_email_html(
    lead: dict,
    insights: dict,
    messages: list[dict],
) -> str:
    tier   = (insights.get("lead_tier") or "cold").lower()
    accent = TIER_ACCENT.get(tier, "#3A5F8A")

    # Contact — only rendered if at least one field exists
    lead_name  = lead.get("name")
    lead_email = lead.get("email")
    lead_phone = lead.get("phone")
    has_contact = any([lead_name, lead_email, lead_phone])

    contact_rows = (
        _kv("Name",  lead_name)  +
        _kv("Email", lead_email) +
        _kv("Phone", lead_phone)
    )

    # Overview — tier badge + up to 3 optional fields
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

    # AI text
    ai_summary  = insights.get("ai_summary")  or "No summary available."
    ai_insights = insights.get("ai_insights") or "No insights available."

    message_rows = _render_messages(messages)

    # Contact block is fully omitted when no data
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
          New Lead
        </div>
        <div style="font-size:22px;font-weight:700;color:#1A202C;">
          {lead_name or "Unknown Lead"}
        </div>
      </td>
    </tr>

    <tr><td style="padding:0 36px;">
      <hr style="border:none;border-top:1px solid #EAEDF0;margin:0;"/>
    </td></tr>

    <!-- Contact (conditional) -->
    {contact_block}

    <!-- Overview -->
    <tr><td style="padding:20px 36px 0;">
      <div style="font-size:10px;font-weight:700;letter-spacing:1.5px;
                  text-transform:uppercase;color:#9AA5B4;margin-bottom:10px;">
        Overview
      </div>
      <table width="100%" cellpadding="0" cellspacing="0">{overview_rows}</table>
    </td></tr>

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
        Auto-generated by your CRM system. Do not reply to this email.
      </td>
    </tr>

  </table>
  </td></tr>
</table>

</body>
</html>"""


# ──────────────────────────────────────────────────────────────
# Public entry point
# ──────────────────────────────────────────────────────────────

async def send_lead_insight_email(
    *,
    insights: dict[str, Any],
    lead: dict[str, Any],
    messages: list[dict],
    recipients: list[str],
) -> None:
    """
    Build and send the lead-insight email.

    Args:
        insights:   Parsed insights dict from AI extraction.
        lead:       Parsed lead dict (name / email / phone — all optional).
        messages:   Conversation as list of {role, content}.
        recipients: Agency email address(es).
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