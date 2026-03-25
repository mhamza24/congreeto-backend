"""
app/modules/email/email.py
──────────────────────────
All outbound email logic for Veloce.

Sections
────────
  A. Brand & shared helpers
  B. Shared HTML shell  (_render_shell)
  C. Customer-facing acknowledgement templates
       build_contact_confirmation_html()
       build_demo_confirmation_html()
       build_affiliation_confirmation_html()
  D. Internal notification HTML builders
       _build_internal_contact_html()
       _build_internal_demo_html()
       _build_internal_affiliation_html()
  E. Lead insight email builders (property chatbot + website B2B)
       build_lead_email_html()
       build_website_lead_email_html()
  F. Shared lead-email shell  (_render_email_shell)
  G. Public send methods
       send_contact_inquiry_email()        ← contact form
       send_demo_inquiry_email()           ← demo request
       send_affiliation_inquiry_email()    ← affiliation application
       send_lead_insight_email()           ← property chatbot lead
       send_website_lead_insight_email()   ← website B2B lead
  H. Conversation follow-up email (sent to visitor after chat ends)
       build_conversation_followup_html()  ← HTML builder
       send_conversation_followup_email()  ← public send method
"""

from __future__ import annotations
from typing import Any

from fastapi_mail import FastMail, MessageSchema, MessageType
from app.config.email import conf as email_config
from app.config.settings import get_settings

import logging

logger   = logging.getLogger(__name__)
settings = get_settings()
fm       = FastMail(email_config)


# ══════════════════════════════════════════════════════════════
# A. Brand palette & tier accents
# ══════════════════════════════════════════════════════════════

BRAND = {
    "brown":       "#A47764",
    "burntOrange": "#CC5500",
    "teal":        "#069494",
    "white":       "#FFFFFF",
    "offWhite":    "#FAF9F8",
    "textDark":    "#1A1A1A",
    "textMid":     "#4A4A4A",
    "textLight":   "#8A8A8A",
    "border":      "#E8E0DC",
}

TIER_ACCENT = {
    "hot":     "#D93025",
    "warm":    "#E8780C",
    "nurture": "#0F7B6C",
    "cold":    "#3A5F8A",
}


# ══════════════════════════════════════════════════════════════
# B. Shared customer-facing shell
# ══════════════════════════════════════════════════════════════

def _render_shell(*, first_name: str, body_html: str) -> str:
    """
    Wraps body_html in the branded Veloce email shell.
    Used for all customer-facing acknowledgement emails.
    """
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Veloce</title>
</head>
<body style="margin:0;padding:0;background:{BRAND['offWhite']};
             font-family:'Georgia',serif;">

<table width="100%" cellpadding="0" cellspacing="0"
       style="background:{BRAND['offWhite']};padding:40px 16px;">
  <tr><td align="center">

  <table width="560" cellpadding="0" cellspacing="0"
         style="max-width:560px;background:{BRAND['white']};
                border-radius:4px;
                box-shadow:0 1px 8px rgba(0,0,0,.06);
                overflow:hidden;">

    <!-- Top accent bar: brown | burntOrange | teal -->
    <tr>
      <td style="font-size:0;line-height:0;height:5px;">
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td style="background:{BRAND['brown']};width:33.3%;height:5px;">&nbsp;</td>
            <td style="background:{BRAND['burntOrange']};width:33.3%;height:5px;">&nbsp;</td>
            <td style="background:{BRAND['teal']};width:33.4%;height:5px;">&nbsp;</td>
          </tr>
        </table>
      </td>
    </tr>

    <!-- Logo / wordmark -->
    <tr>
      <td style="padding:32px 40px 24px;border-bottom:1px solid {BRAND['border']};">
        <a href="https://getveloce.com" target="_blank"
           style="text-decoration:none;display:inline-block;">
          <span style="font-family:'Georgia',serif;font-size:26px;font-weight:700;
                        letter-spacing:-0.5px;color:{BRAND['brown']};">Vel</span><span
               style="font-family:'Georgia',serif;font-size:26px;font-weight:700;
                       letter-spacing:-0.5px;color:{BRAND['teal']};">oce</span>
        </a>
      </td>
    </tr>

    <!-- Greeting -->
    <tr>
      <td style="padding:32px 40px 0;">
        <p style="margin:0 0 20px;font-size:15px;color:{BRAND['textDark']};line-height:1.6;">
          Hi {first_name},
        </p>
      </td>
    </tr>

    <!-- Dynamic body -->
    <tr>
      <td style="padding:0 40px 32px;">
        {body_html}
      </td>
    </tr>

    <!-- Divider -->
    <tr>
      <td style="padding:0 40px;">
        <hr style="border:none;border-top:1px solid {BRAND['border']};margin:0;" />
      </td>
    </tr>

    <!-- Sign-off -->
    <tr>
      <td style="padding:28px 40px;">
        <p style="margin:0 0 4px;font-size:13px;color:{BRAND['textMid']};line-height:1.6;">
          Warm regards,
        </p>
        <p style="margin:0 0 2px;font-size:13px;font-weight:700;color:{BRAND['textDark']};">
          Veloce Customer Service Team
        </p>
        <a href="https://getveloce.com" target="_blank"
           style="font-size:12px;color:{BRAND['teal']};text-decoration:none;">
          getveloce.com
        </a>
      </td>
    </tr>

    <!-- Divider -->
    <tr>
      <td style="padding:0 40px;">
        <hr style="border:none;border-top:1px solid {BRAND['border']};margin:0;" />
      </td>
    </tr>

    <!-- Footer: privacy notice -->
    <tr>
      <td style="padding:20px 40px 28px;">
        <p style="margin:0 0 6px;font-size:10px;font-weight:700;
                  text-transform:uppercase;letter-spacing:1px;color:{BRAND['textLight']};">
          Privacy &amp; Confidentiality Notice
        </p>
        <p style="margin:0;font-size:10px;color:{BRAND['textLight']};line-height:1.65;">
          This email and any attachments are confidential and intended solely for the
          addressee. If you have received this email in error, please notify the sender
          immediately and delete it from your system. Any unauthorised use, disclosure,
          or distribution of this communication is prohibited. Veloce respects your
          privacy and handles all personal information in accordance with applicable
          data protection and privacy regulations.
        </p>
      </td>
    </tr>

  </table>
  </td></tr>
</table>

</body>
</html>"""


# ══════════════════════════════════════════════════════════════
# C. Customer-facing acknowledgement templates
# ══════════════════════════════════════════════════════════════

def build_contact_confirmation_html(first_name: str = "there") -> str:
    """Auto-reply sent to the visitor who submitted the contact form."""
    body = f"""
    <p style="margin:0 0 16px;font-size:15px;color:{BRAND['textDark']};line-height:1.75;">
      Thank you for reaching out to Veloce.
    </p>
    <p style="margin:0 0 16px;font-size:15px;color:{BRAND['textDark']};line-height:1.75;">
      We appreciate your interest and confirm that your enquiry has been received.
      Our team is currently reviewing the details and will be in touch with you within
      the next business day.
    </p>

    <table width="100%" cellpadding="0" cellspacing="0" style="margin:24px 0;">
      <tr>
        <td style="border-left:3px solid {BRAND['brown']};background:{BRAND['offWhite']};
                   border-radius:0 4px 4px 0;padding:14px 16px;">
          <p style="margin:0;font-size:12px;color:{BRAND['textMid']};line-height:1.65;">
            Please note this is an automated, unmonitored email and replies to this
            address will not be received.
          </p>
        </td>
      </tr>
    </table>

    <p style="margin:0 0 6px;font-size:15px;color:{BRAND['textDark']};line-height:1.75;">
      If you would like to speak with someone directly or add further details to your
      enquiry, please contact us at:
    </p>
    <p style="margin:0;font-size:15px;">
      <a href="mailto:contact@getveloce.com"
         style="color:{BRAND['teal']};text-decoration:none;font-weight:600;">
        contact@getveloce.com
      </a>
    </p>
    """
    return _render_shell(first_name=first_name, body_html=body)


def build_demo_confirmation_html(first_name: str = "there") -> str:
    """Auto-reply sent to the visitor who requested a live demo."""
    body = f"""
    <p style="margin:0 0 16px;font-size:15px;color:{BRAND['textDark']};line-height:1.75;">
      Thank you for your interest in Veloce.
    </p>
    <p style="margin:0 0 16px;font-size:15px;color:{BRAND['textDark']};line-height:1.75;">
      We&#8217;re pleased to confirm that your demo request has been received.
      Our team is currently reviewing your details, and a relevant member of our team
      will be in touch within the next business day to schedule your live demo.
    </p>

    <table width="100%" cellpadding="0" cellspacing="0" style="margin:24px 0;">
      <tr>
        <td style="border-left:3px solid {BRAND['teal']};background:{BRAND['offWhite']};
                   border-radius:0 4px 4px 0;padding:14px 16px;">
          <p style="margin:0 0 6px;font-size:12px;font-weight:700;
                    text-transform:uppercase;letter-spacing:.8px;color:{BRAND['teal']};">
            What to expect
          </p>
          <p style="margin:0;font-size:12px;color:{BRAND['textMid']};line-height:1.65;">
            We look forward to walking you through the Veloce Intelligence Chatbox in a
            live environment, tailored to your business, and showing you how it can
            elevate your customer experience and lead engagement.
          </p>
        </td>
      </tr>
    </table>

    <table width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 24px;">
      <tr>
        <td style="border-left:3px solid {BRAND['brown']};background:{BRAND['offWhite']};
                   border-radius:0 4px 4px 0;padding:14px 16px;">
          <p style="margin:0;font-size:12px;color:{BRAND['textMid']};line-height:1.65;">
            Please note this is an automated, unmonitored email and replies to this
            address will not be received.
          </p>
        </td>
      </tr>
    </table>

    <p style="margin:0 0 6px;font-size:15px;color:{BRAND['textDark']};line-height:1.75;">
      If you have any follow-up questions in the meantime, please contact us at:
    </p>
    <p style="margin:0;font-size:15px;">
      <a href="mailto:contact@getveloce.com"
         style="color:{BRAND['teal']};text-decoration:none;font-weight:600;">
        contact@getveloce.com
      </a>
    </p>
    """
    return _render_shell(first_name=first_name, body_html=body)


def build_affiliation_confirmation_html(first_name: str = "there") -> str:
    """Auto-reply sent to the applicant who submitted an affiliation inquiry."""
    body = f"""
    <p style="margin:0 0 16px;font-size:15px;color:{BRAND['textDark']};line-height:1.75;">
      Thank you for your interest in affiliating with Veloce.
    </p>
    <p style="margin:0 0 16px;font-size:15px;color:{BRAND['textDark']};line-height:1.75;">
      We&#8217;re pleased to confirm that your affiliation application has been received.
      Our team will review your details and be in touch within the next
      <strong>next business day</strong> to discuss the next steps.
    </p>

    <table width="100%" cellpadding="0" cellspacing="0" style="margin:24px 0;">
      <tr>
        <td style="border-left:3px solid {BRAND['teal']};background:{BRAND['offWhite']};
                   border-radius:0 4px 4px 0;padding:14px 16px;">
          <p style="margin:0 0 6px;font-size:12px;font-weight:700;
                    text-transform:uppercase;letter-spacing:.8px;color:{BRAND['teal']};">
            What happens next
          </p>
          <p style="margin:0;font-size:12px;color:{BRAND['textMid']};line-height:1.65;">
            Our partnerships team will verify your submitted details, including your
            ABN&nbsp;/ ACN and business structure, before reaching out to confirm your
            affiliation status and outline any onboarding requirements.
          </p>
        </td>
      </tr>
    </table>

    <table width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 24px;">
      <tr>
        <td style="border-left:3px solid {BRAND['brown']};background:{BRAND['offWhite']};
                   border-radius:0 4px 4px 0;padding:14px 16px;">
          <p style="margin:0;font-size:12px;color:{BRAND['textMid']};line-height:1.65;">
            Please note this is an automated, unmonitored email and replies to this
            address will not be received.
          </p>
        </td>
      </tr>
    </table>

    <p style="margin:0 0 6px;font-size:15px;color:{BRAND['textDark']};line-height:1.75;">
      If you have any questions in the meantime, please reach out to us directly at:
    </p>
    <p style="margin:0;font-size:15px;">
      <a href="mailto:contact@getveloce.com"
         style="color:{BRAND['teal']};text-decoration:none;font-weight:600;">
        contact@getveloce.com
      </a>
    </p>
    """
    return _render_shell(first_name=first_name, body_html=body)


# ══════════════════════════════════════════════════════════════
# D. Internal notification HTML builders
# ══════════════════════════════════════════════════════════════

def _build_internal_contact_html(
    *,
    full_name: str,
    email: str,
    company: str,
    subject: str,
    message: str,
) -> str:
    """Internal team notification for a new contact form submission."""
    rows = (
        _kv("Name",    full_name) +
        _kv("Email",   email)     +
        _kv("Company", company)   +
        _kv("Subject", subject)
    )
    return _render_email_shell(
        accent=TIER_ACCENT["warm"],
        header_label="New Contact Enquiry",
        lead_name=full_name,
        contact_block="",
        overview_rows=rows,
        ai_summary=message,
        ai_insights="",
        message_rows="",
        recommended_action="Reply to this enquiry within one business day.",
    )


def _build_internal_demo_html(
    *,
    full_name: str,
    email: str,
    company: str,
    company_website: str | None,
    property_sectors: list[str],
    states: list[str],
    message: str,
) -> str:
    """Internal team notification for a new demo request submission."""
    accent = TIER_ACCENT["hot"]

    sectors_html = _pill_list(property_sectors, accent)
    states_html  = _pill_list(states, accent)

    rows = (
        _kv("Name",             full_name)      +
        _kv("Email",            email)           +
        _kv("Company",          company)         +
        _kv("Website",          company_website) +
        _kv("Property Sectors", sectors_html)    +
        _kv("States",           states_html)
    )
    return _render_email_shell(
        accent=accent,
        header_label="New Demo Request",
        lead_name=full_name,
        contact_block="",
        overview_rows=rows,
        ai_summary=message,
        ai_insights="",
        message_rows="",
        recommended_action="Schedule a live demo within one business day.",
    )


def _build_internal_affiliation_html(
    *,
    full_name: str,
    email: str,
    phone: str | None,
    category: str | None,
    abn: str | None,
    acn: str | None,
    legal_entity_name: str | None,
    gst_applicable: str | None,
    company_type: str | None,
) -> str:
    """
    Internal team notification for a new affiliation application.
    Renders only the collected form data — no AI summary or insights.
    """
    accent = TIER_ACCENT["warm"]

    contact_rows = (
        _kv("Name",  full_name) +
        _kv("Email", email)     +
        _kv("Phone", phone)
    )

    business_rows = (
        _kv("Category",       (category or "").replace("_", " ").title() or None)     +
        _kv("ABN",            abn)                                                     +
        _kv("ACN",            acn)                                                     +
        _kv("Legal Entity",   legal_entity_name)                                       +
        _kv("GST Applicable", (gst_applicable or "").title() or None)                 +
        _kv("Company Type",   (company_type or "").replace("_", " ").title() or None)
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>New Affiliation Application</title>
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
          New Affiliation Application
        </div>
        <div style="font-size:22px;font-weight:700;color:#1A202C;">
          {full_name}
        </div>
      </td>
    </tr>

    <tr><td style="padding:0 36px;">
      <hr style="border:none;border-top:1px solid #EAEDF0;margin:0;"/>
    </td></tr>

    <!-- Contact Details -->
    <tr><td style="padding:20px 36px 0;">
      <div style="font-size:10px;font-weight:700;letter-spacing:1.5px;
                  text-transform:uppercase;color:#9AA5B4;margin-bottom:10px;">
        Contact Details
      </div>
      <table width="100%" cellpadding="0" cellspacing="0">
        {contact_rows}
      </table>
    </td></tr>

    <tr><td style="padding:16px 36px 0;">
      <hr style="border:none;border-top:1px solid #EAEDF0;margin:0;"/>
    </td></tr>

    <!-- Business Details -->
    <tr><td style="padding:20px 36px 0;">
      <div style="font-size:10px;font-weight:700;letter-spacing:1.5px;
                  text-transform:uppercase;color:#9AA5B4;margin-bottom:10px;">
        Business Details
      </div>
      <table width="100%" cellpadding="0" cellspacing="0">
        {business_rows}
      </table>
    </td></tr>

    <tr><td style="padding:16px 36px 0;">
      <hr style="border:none;border-top:1px solid #EAEDF0;margin:0;"/>
    </td></tr>

    <!-- Recommended Action -->
    <tr><td style="padding:20px 36px 28px;">
      <div style="font-size:10px;font-weight:700;letter-spacing:1.5px;
                  text-transform:uppercase;color:#9AA5B4;margin-bottom:10px;">
        Recommended Action
      </div>
      <div style="font-size:13px;color:#FFFFFF;line-height:1.65;
                  background:{accent};border-radius:8px;padding:12px 16px;
                  font-weight:500;">
        Review applicant details and verify ABN / ACN before responding.
      </div>
    </td></tr>

    <!-- Footer -->
    <tr>
      <td style="padding:20px 36px 28px;text-align:center;
                 font-size:11px;color:#B0BAC9;
                 border-top:1px solid #EAEDF0;">
        Auto-generated by Veloce. Do not reply to this email.
      </td>
    </tr>

  </table>
  </td></tr>
</table>

</body>
</html>"""


# ══════════════════════════════════════════════════════════════
# E. Lead insight email builders (property chatbot + website B2B)
# ══════════════════════════════════════════════════════════════

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
        align   = "left"    if is_lead else "right"
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
    if not value:
        return ""
    return f"""
    <tr>
      <td style="padding:5px 0;font-size:12px;color:#718096;
                 width:30%;vertical-align:top;">{label}</td>
      <td style="padding:5px 0;font-size:13px;color:#1A202C;font-weight:500;">{value}</td>
    </tr>"""


def _pill_list(items: list[str] | None, accent: str) -> str | None:
    if not items:
        return None
    pills = "".join(
        f'<span style="display:inline-block;margin:2px 3px 2px 0;padding:2px 9px;'
        f'border-radius:12px;background:#F4F6F9;border:1px solid #D8DDE6;'
        f'font-size:11px;color:#2D3748;">{item}</span>'
        for item in items
    )
    return f'<div style="line-height:2;">{pills}</div>'


def build_lead_email_html(
    lead: dict,
    insights: dict,
    messages: list[dict],
) -> str:
    """Builds the lead notification email for PROPERTY chatbot conversations."""
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

    ai_summary   = insights.get("ai_summary")  or "No summary available."
    ai_insights  = insights.get("ai_insights") or "No insights available."
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


def build_website_lead_email_html(
    lead: dict,
    insights: dict,
    messages: list[dict],
) -> str:
    """
    Builds the lead notification email for WEBSITE (B2B) conversations.

    Column remapping mirrors upsert_website_conversation_insights:
      budget_currency   → subscription preference
      suburbs_mentioned → pain points
      cities_mentioned  → business operating locations
      property_types    → business type (single-item array)
      budget_min/max    → always None (not rendered)
    """
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

    score = insights.get("lead_score")

    raw_intent     = insights.get("intent") or ""
    intent_display = raw_intent.replace("_", " ").title() or None

    business_type_arr = insights.get("property_types")
    business_type = (
        business_type_arr[0].replace("_", " ").title()
        if business_type_arr else None
    )

    business_location_arr = insights.get("cities_mentioned")
    business_location = (
        ", ".join(business_location_arr)
        if business_location_arr else None
    )

    sub_pref = (insights.get("budget_currency") or "").title() or None
    timeline = (insights.get("timeline") or "").replace("_", " ").title() or None

    overview_rows = (
        _kv("Lead Tier",     tier_badge)                                      +
        _kv("Score",         f"{score}/100" if score is not None else None)   +
        _kv("Intent",        intent_display)                                  +
        _kv("Business Type", business_type)                                   +
        _kv("Location",      business_location)                               +
        _kv("Subscription",  sub_pref)                                        +
        _kv("Timeline",      timeline)
    )

    pain_points      = insights.get("suburbs_mentioned")
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


# ══════════════════════════════════════════════════════════════
# F. Shared lead-email HTML shell
# ══════════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════════
# G. Public send methods
# ══════════════════════════════════════════════════════════════

async def send_contact_inquiry_email(
    *,
    contact: dict[str, Any],
    recipients: list[str],
) -> None:
    """
    Fired when a visitor submits the contact form on getveloce.com.

    Sends:
      1. Acknowledgement → visitor (contact["email"])
      2. Internal notification → Veloce team (recipients)
    """
    first_name = contact.get("first_name") or "there"
    full_name  = f"{contact.get('first_name', '')} {contact.get('last_name', '')}".strip()

    # 1. Acknowledgement → visitor
    await fm.send_message(MessageSchema(
        subject="We've received your enquiry — Veloce",
        recipients=[contact["email"]],
        body=build_contact_confirmation_html(first_name=first_name),
        subtype=MessageType.html,
    ))

    # 2. Internal notification → team
    await fm.send_message(MessageSchema(
        subject=f"[Contact Form] {contact.get('subject') or 'New Enquiry'} — {full_name}",
        recipients=recipients,
        body=_build_internal_contact_html(
            full_name=full_name,
            email=contact["email"],
            company=contact.get("company_name") or "N/A",
            subject=contact.get("subject") or "No Subject",
            message=contact.get("message") or "",
        ),
        subtype=MessageType.html,
    ))

    logger.info(
        f"Contact inquiry emails sent | submitter={contact['email']} | team={recipients}"
    )


async def send_demo_inquiry_email(
    *,
    demo: dict[str, Any],
    recipients: list[str],
) -> None:
    """
    Fired when a visitor submits the demo request form on getveloce.com.

    Sends:
      1. Acknowledgement → visitor (demo["email"])
      2. Internal notification → Veloce team (recipients)
    """
    first_name = demo.get("first_name") or "there"
    full_name  = f"{demo.get('first_name', '')} {demo.get('last_name', '')}".strip()

    # 1. Acknowledgement → visitor
    await fm.send_message(MessageSchema(
        subject="Your Veloce demo request has been received",
        recipients=[demo["email"]],
        body=build_demo_confirmation_html(first_name=first_name),
        subtype=MessageType.html,
    ))

    # 2. Internal notification → team
    await fm.send_message(MessageSchema(
        subject=f"[Demo Request] {full_name} — {demo.get('company_name') or 'Unknown Company'}",
        recipients=recipients,
        body=_build_internal_demo_html(
            full_name=full_name,
            email=demo["email"],
            company=demo.get("company_name") or "N/A",
            company_website=demo.get("company_website"),
            property_sectors=demo.get("property_sectors") or [],
            states=demo.get("states") or [],
            message=demo.get("message") or "",
        ),
        subtype=MessageType.html,
    ))

    logger.info(
        f"Demo inquiry emails sent | submitter={demo['email']} | team={recipients}"
    )


async def send_affiliation_inquiry_email(
    *,
    inquiry: dict[str, Any],
    recipients: list[str],
) -> None:
    """
    Fired when a visitor submits the affiliation form on getveloce.com.

    Sends:
      1. Acknowledgement → applicant (inquiry["email"])
      2. Internal notification → Veloce team (recipients)
    """
    first_name = inquiry.get("first_name") or "there"
    full_name  = f"{inquiry.get('first_name', '')} {inquiry.get('last_name', '')}".strip()

    # 1. Acknowledgement → applicant
    await fm.send_message(MessageSchema(
        subject="Your Veloce affiliation application has been received",
        recipients=[inquiry["email"]],
        body=build_affiliation_confirmation_html(first_name=first_name),
        subtype=MessageType.html,
    ))

    # 2. Internal notification → team
    await fm.send_message(MessageSchema(
        subject=f"[Affiliation] {full_name} — {(inquiry.get('company_type') or 'Unknown Type').replace('_', ' ').title()}",
        recipients=recipients,
        body=_build_internal_affiliation_html(
            full_name=full_name,
            email=inquiry["email"],
            phone=inquiry.get("phone"),
            category=inquiry.get("category"),
            abn=inquiry.get("abn"),
            acn=inquiry.get("acn"),
            legal_entity_name=inquiry.get("legal_entity_name"),
            gst_applicable=inquiry.get("gst_applicable"),
            company_type=inquiry.get("company_type"),
        ),
        subtype=MessageType.html,
    ))

    logger.info(
        f"Affiliation inquiry emails sent | applicant={inquiry['email']} | team={recipients}"
    )


async def send_lead_insight_email(
    *,
    insights: dict[str, Any],
    lead: dict[str, Any],
    messages: list[dict],
    recipients: list[str],
) -> None:
    """Build and send the lead-insight email for PROPERTY chatbot conversations."""
    tier      = (insights.get("lead_tier") or "lead").upper()
    lead_name = lead.get("name") or "New Lead"

    await fm.send_message(MessageSchema(
        subject=f"[{tier}] New Lead: {lead_name}",
        recipients=recipients,
        body=build_lead_email_html(lead=lead, insights=insights, messages=messages),
        subtype=MessageType.html,
    ))

    logger.info(
        f"Sent lead email to {recipients} for lead {lead_name} with tier {tier}"
    )


async def send_website_lead_insight_email(
    *,
    insights: dict[str, Any],
    lead: dict[str, Any],
    messages: list[dict],
    recipients: list[str],
) -> None:
    """Build and send the lead-insight email for WEBSITE (B2B) conversations."""
    tier      = (insights.get("lead_tier") or "lead").upper()
    lead_name = lead.get("name") or "New Visitor"

    raw_intent = (insights.get("intent") or "").replace("_", " ").title()
    subject = (
        f"[{tier}] {raw_intent} — {lead_name}"
        if raw_intent
        else f"[{tier}] Website Enquiry: {lead_name}"
    )

    await fm.send_message(MessageSchema(
        subject=subject,
        recipients=recipients,
        body=build_website_lead_email_html(lead=lead, insights=insights, messages=messages),
        subtype=MessageType.html,
    ))

    logger.info(
        f"Sent website lead email to {recipients} for lead {lead_name} with intent {raw_intent}"
    )


# ══════════════════════════════════════════════════════════════
# H. Conversation follow-up email  (sent directly to the visitor)
# ══════════════════════════════════════════════════════════════

def build_conversation_followup_html(
    *,
    first_name: str,
    topics: list[str],
    messages: list[dict],
    ai_summary: str,
    website_name: str = "Veloce",
) -> str:
    """
    A personalised follow-up email sent to the visitor after their chatbot
    conversation ends (only when their email was captured during the chat).
    """
    topic_pills = ""
    if topics:
        pills = "".join(
            f'<span style="display:inline-block;margin:3px 4px 3px 0;'
            f'padding:4px 12px;border-radius:20px;'
            f'background:{BRAND["offWhite"]};border:1px solid {BRAND["border"]};'
            f'font-size:12px;color:{BRAND["textDark"]};font-family:Georgia,serif;">'
            f'{topic}</span>'
            for topic in topics
        )
        topic_pills = f"""
        <table width="100%" cellpadding="0" cellspacing="0" style="margin:20px 0 0;">
          <tr>
            <td>
              <p style="margin:0 0 10px;font-size:10px;font-weight:700;
                        text-transform:uppercase;letter-spacing:1.2px;
                        color:{BRAND['textLight']};">
                Topics we covered
              </p>
              <div style="line-height:2.2;">{pills}</div>
            </td>
          </tr>
        </table>"""

    summary_block = ""
    if ai_summary:
        summary_block = f"""
        <table width="100%" cellpadding="0" cellspacing="0" style="margin:24px 0 0;">
          <tr>
            <td style="border-left:3px solid {BRAND['teal']};padding-left:14px;">
              <p style="margin:0 0 6px;font-size:10px;font-weight:700;
                        text-transform:uppercase;letter-spacing:1px;
                        color:{BRAND['teal']};">
                Conversation summary
              </p>
              <p style="margin:0;font-size:13px;color:{BRAND['textMid']};
                        line-height:1.75;font-family:Georgia,serif;">
                {ai_summary}
              </p>
            </td>
          </tr>
        </table>"""

    transcript_block = ""
    if messages:
        transcript_rows = _render_messages(messages)
        transcript_block = f"""
        <table width="100%" cellpadding="0" cellspacing="0" style="margin:24px 0 0;">
          <tr>
            <td>
              <p style="margin:0 0 12px;font-size:10px;font-weight:700;
                        text-transform:uppercase;letter-spacing:1.2px;
                        color:{BRAND['textLight']};">
                Your conversation
              </p>
              <table width="100%" cellpadding="0" cellspacing="0">
                {transcript_rows}
              </table>
            </td>
          </tr>
        </table>"""

    body = f"""
    <p style="margin:0 0 16px;font-size:15px;color:{BRAND['textDark']};line-height:1.75;">
      Thank you for chatting with us on
      <a href="https://getveloce.com" target="_blank"
         style="color:{BRAND['teal']};text-decoration:none;font-weight:600;">
        getveloce.com</a>.
      We wanted to send you a quick summary of your conversation so you have it
      handy for future reference.
    </p>

    {topic_pills}
    {summary_block}

    <table width="100%" cellpadding="0" cellspacing="0" style="margin:28px 0 0;">
      <tr><td style="border-top:1px solid {BRAND['border']};font-size:0;line-height:0;">&nbsp;</td></tr>
    </table>

    {transcript_block}

    <table width="100%" cellpadding="0" cellspacing="0" style="margin:28px 0 0;">
      <tr><td style="border-top:1px solid {BRAND['border']};font-size:0;line-height:0;">&nbsp;</td></tr>
    </table>

    <table width="100%" cellpadding="0" cellspacing="0" style="margin:24px 0 0;">
      <tr>
        <td style="background:{BRAND['offWhite']};border-left:3px solid {BRAND['brown']};
                   border-radius:0 4px 4px 0;padding:14px 16px;">
          <p style="margin:0 0 6px;font-size:13px;color:{BRAND['textDark']};line-height:1.65;">
            Have more questions or ready to take the next step?
          </p>
          <p style="margin:0;font-size:13px;">
            <a href="mailto:contact@getveloce.com"
               style="color:{BRAND['teal']};text-decoration:none;font-weight:600;">
              contact@getveloce.com
            </a>
          </p>
        </td>
      </tr>
    </table>

    <p style="margin:20px 0 0;font-size:11px;color:{BRAND['textLight']};line-height:1.6;">
      Please note this is an automated email. Replies to this address will not be received.
    </p>
    """

    return _render_shell(first_name=first_name, body_html=body)


async def send_conversation_followup_email(
    *,
    lead_email: str,
    lead_name: str | None,
    topics: list[str],
    messages: list[dict],
    ai_summary: str = "",
) -> None:
    """
    Sent directly to the visitor after their chatbot conversation ends,
    only when their email was captured during the session.
    """
    first_name = (lead_name or "").split()[0] if lead_name else "there"

    await fm.send_message(MessageSchema(
        subject="Your conversation with Veloce — recap & next steps",
        recipients=[lead_email],
        body=build_conversation_followup_html(
            first_name=first_name,
            topics=topics,
            messages=messages,
            ai_summary=ai_summary,
        ),
        subtype=MessageType.html,
    ))

    logger.info(f"Conversation follow-up email sent to {lead_email}")