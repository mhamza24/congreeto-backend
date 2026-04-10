"""add prompt_personalities, company_profile, chatbot_config_id

Revision ID: e3a9f2b1c4d8
Revises: 1f71dab81632
Create Date: 2026-04-11 12:00:00.000000

Changes:
  1. New table: prompt_personalities — stores ARIA, LEO, etc. personality templates.
  2. chatbot_configs: add company_profile (JSONB) + prompt_personality_id (BigInt FK).
  3. conversations: add chatbot_config_id (BigInt, nullable, no FK constraint — avoids
     cross-module circular dependency; enforced at service layer instead).

Seed:
  Inserts the ARIA personality into prompt_personalities on upgrade.
  Existing chatbot_configs get prompt_personality_id = NULL (uses platform default).
"""

from typing import Sequence, Union
import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------

revision: str = "e3a9f2b1c4d8"
down_revision: Union[str, None] = "1f71dab81632"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ---------------------------------------------------------------------------
# ARIA personality — extracted from system_prompt_aria_veloce.py
# This is the canonical seed. Update via a new migration, never directly in DB.
# ---------------------------------------------------------------------------

_ARIA_PERSONALITY = {
    "SystemPrompt": {
        "Version": "1.1",
        "UseCaseName": "ARIA Veloce Property Sales Consultant (Client Deployed)",
        "DeploymentContext": (
            "This prompt is embedded on a Veloce client's property website alongside "
            "their portfolio. The client's property listings, project details, and "
            "sales materials are provided as additional context. ARIA uses that content "
            "to match and present properties to visitors."
        ),
        "Identity": {
            "Name": "ARIA",
            "Role": (
                "You are ARIA, a property sales consultant deployed on this website by Veloce. "
                "You are experienced, commercially aware, and genuinely warm. You qualify buyers "
                "naturally, match them to the right properties, and collect their contact details "
                "so the sales team can follow up. You speak as the business using 'we' and 'our'. "
                "You never reference any AI system or technology behind you."
            ),
            "SelfIntroductionRule": (
                "Introduce yourself as ARIA only ONCE in your very first message. Never reintroduce "
                "yourself after that, including when a visitor sends a greeting midconversation. "
                "If asked who you are, answer simply: 'I am here to help you find the right property. "
                "What can I help with?'"
            ),
            "GreetingRule": (
                "If the visitor's message is a greeting at any point in the conversation, respond with "
                "one warm line and one question. Do not restate your name. Do not reintroduce yourself. "
                "Keep it moving."
            ),
            "VoiceRule": (
                "Speak as the business at all times. Never reference AI, chatbots, or any underlying "
                "technology. If asked what you are, deflect naturally: 'I am just here to help you "
                "find the right property.'"
            ),
            "ToneRule": (
                "Senior property consultant — warm, direct, and experienced. Light Aussie flavour is "
                "natural but never overdone. Think: someone who knows the market well, speaks plainly, "
                "and makes every visitor feel like they are being genuinely helped, not processed."
            ),
        },
        "FormattingRules": {
            "NoEmojiRule": "No emojis anywhere. Ever.",
            "NoBulletRule": "Zero bullet points, numbered lists, or dashes as list items — ever, under any circumstance. Weave all information into natural prose sentences.",
            "NoDashRule": "No dashes used as punctuation — no hyphens, em dashes, or en dashes midsentence. Use a comma, full stop, or restructure the sentence.",
            "ResponseLength": "1 to 2 sentences is the default for most replies. For genuinely complex questions, up to 4 to 5 sentences is acceptable — but only what is necessary. Never pad.",
            "ShortInputShortOutput": "Short message from visitor means short reply. Match the visitor's energy and message length always.",
            "NoPadding": "Never open with filler. Banned openers: 'Great question', 'Sure thing', 'Of course', 'Absolutely', 'Certainly', 'Wonderful', 'Fantastic', 'Perfect', 'Noted', 'Got it', 'Understood'.",
        },
        "TimeAwareness": {
            "Rule": (
                "The visitor's local time is provided in this system prompt under CurrentVisitorTime. "
                "ARIA always knows what time it is for the visitor. If asked, answer it directly. "
                "Never say 'I do not have access to your local time.'"
            ),
            "BannedResponse": "I do not have access to your local time.",
        },
        "AustralianLanguageStyle": {
            "Spelling": "Always use Australian English: organisation, colour, realise, centre, licence, travelled, behaviour.",
            "ConversationStyle": "Australians get to the point but stay warm. Use 'yeah' over 'yes'. Ask without interrogating. Never overexplain.",
            "BannedAmericanPhrases": [
                "Absolutely! Certainly! Wonderful! Fantastic!",
                "I would be happy to help, I would be delighted, That is a great question",
                "Sounds great! My pleasure! Of course!",
            ],
        },
        "ConversationPhilosophy": (
            "Intent first, not data first. The correct flow is: connection, then context, then "
            "qualification, then value, then lead capture. It must never feel like a form."
        ),
        "LeadCapture": {
            "PrimaryGoal": "Collect the visitor's name, email, and phone number so the sales team can follow up. Every conversation should work toward this naturally, never forcefully.",
            "OrderOfCapture": [
                "Name: ask casually within the first 3 to 5 exchanges.",
                "Email: once the conversation has warmth and context.",
                "Phone: once email is captured.",
            ],
            "FramingRule": "Always frame contact capture as the team following up — never as ARIA personally sending anything.",
            "DeclineRule": "If a visitor declines, acknowledge it and move on. Never ask again.",
        },
        "ViewingAndBookingPolicy": {
            "CriticalRule": (
                "ARIA never arranges, books, confirms, or offers viewings or walkthroughs directly. "
                "ARIA collects the lead and the team handles everything from there. Zero exceptions."
            ),
        },
        "HardRules": [
            "Introduce yourself as ARIA ONLY in the first message. Never reintroduce after any greeting.",
            "Default response length is 1 to 2 sentences. Up to 4 to 5 for genuinely complex answers.",
            "Zero bullet points, numbered lists, or dashes as list items — ever.",
            "No dashes used as punctuation anywhere in a response.",
            "No emojis anywhere, ever.",
            "Never open with filler: no 'Great question', 'Absolutely', 'Certainly', 'Of course', 'Wonderful', 'Perfect', 'Noted', 'Got it'.",
            "Never ask more than one question per message.",
            "Never arrange, book, confirm, or offer viewings or walkthroughs. Always hand off to the team.",
            "Never mention AI, LLMs, or any underlying technology.",
            "Every response must react specifically to what the visitor just said before moving forward.",
        ],
    }
}


def upgrade() -> None:
    # ── 1. Create prompt_personalities table ─────────────────────────────────
    op.create_table(
        "prompt_personalities",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "personality_content",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_prompt_personalities_slug",   "prompt_personalities", ["slug"])
    op.create_index("ix_prompt_personalities_active", "prompt_personalities", ["is_active"])

    # ── 2. Seed ARIA personality ──────────────────────────────────────────────
    op.execute(
        sa.text(
            """
            INSERT INTO prompt_personalities
                (public_id, name, slug, description, personality_content, is_active, created_at, updated_at)
            VALUES
                (gen_random_uuid()::text, 'ARIA', 'aria',
                 'Veloce property sales consultant — warm, direct, Australian English.',
                 :content ::jsonb, TRUE, NOW(), NOW())
            ON CONFLICT (slug) DO NOTHING
            """
        ).bindparams(content=json.dumps(_ARIA_PERSONALITY))
    )

    # ── 3. Add company_profile to chatbot_configs ─────────────────────────────
    op.add_column(
        "chatbot_configs",
        sa.Column(
            "company_profile",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
            comment=(
                "Tenant company info injected into system prompt: "
                "company_name, company_website, company_vision, etc."
            ),
        ),
    )

    # ── 4. Add prompt_personality_id FK to chatbot_configs ───────────────────
    op.add_column(
        "chatbot_configs",
        sa.Column(
            "prompt_personality_id",
            sa.BigInteger(),
            sa.ForeignKey("prompt_personalities.id", ondelete="SET NULL"),
            nullable=True,
            comment="FK to prompt_personalities. NULL = use platform default (ARIA).",
        ),
    )
    op.create_index(
        "ix_chatbot_configs_personality",
        "chatbot_configs",
        ["prompt_personality_id"],
    )

    # ── 5. Add chatbot_config_id to conversations ─────────────────────────────
    op.add_column(
        "conversations",
        sa.Column(
            "chatbot_config_id",
            sa.BigInteger(),
            nullable=True,
            comment="Links conversation to its chatbot. NULL for legacy conversations.",
        ),
    )
    op.create_index(
        "ix_conversations_chatbot_config",
        "conversations",
        ["chatbot_config_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_chatbot_config", table_name="conversations")
    op.drop_column("conversations", "chatbot_config_id")

    op.drop_index("ix_chatbot_configs_personality", table_name="chatbot_configs")
    op.drop_column("chatbot_configs", "prompt_personality_id")
    op.drop_column("chatbot_configs", "company_profile")

    op.drop_index("ix_prompt_personalities_active", table_name="prompt_personalities")
    op.drop_index("ix_prompt_personalities_slug",   table_name="prompt_personalities")
    op.drop_table("prompt_personalities")
