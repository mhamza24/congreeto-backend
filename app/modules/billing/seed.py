# app/modules/billing/seed.py
"""
Seed plans and addons.
Run once on fresh DB or after truncating plans/addons tables.

Usage:
    from app.modules.billing.seed import seed_plans_and_addons
    await seed_plans_and_addons(db)
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.modules.billing.models import Plan, Addon
from app.core.enums import BillingInterval, AddonType


# =============================================================================
# DEFAULT LIMITS — same for all plans right now
# Update per-plan when you're ready to differentiate
# =============================================================================
DEFAULT_LIMITS = {
    "max_users": 3,
    "max_chatbots": 1,
    "max_conversations_per_month": 750,
    "max_tokens_per_month": 1_000_000,
    "max_tokens_per_conversation": 4_000,
    "max_documents": 120,
    "max_pages_crawled": 50,
    "max_listings": 500,
    "max_storage_mb": 1_000,
}

PLANS = [
    # ── Project Developments ──────────────────────────────────────────────────
    {
        "name": "Project Developments",
        "slug": "project-developments-monthly",
        "description": (
            "Designed for single property development websites with focused traffic. "
            "Recommended for land estates, boutique apartments under 20 units, "
            "small project marketing websites, and individual development landing pages."
        ),
        "billing_interval": BillingInterval.MONTHLY,
        "price_aud_cents": 30_000,  # AUD 300/month
        "price_usd_cents": 20_000,  # USD 200/month
        "is_public": True,
        "sort_order": 1,
        "limits": DEFAULT_LIMITS,
    },
    {
        "name": "Project Developments Annual",
        "slug": "project-developments-annual",
        "description": (
            "Project Developments plan billed annually. Save 20%. "
            "Designed for single property development websites with focused traffic."
        ),
        "billing_interval": BillingInterval.ANNUAL,
        "price_aud_cents": 288_000,  # AUD 300 * 12 * 0.8 = 2880/year
        "price_usd_cents": 192_000,  # USD 200 * 12 * 0.8
        "is_public": True,
        "sort_order": 2,
        "limits": DEFAULT_LIMITS,
    },
    # ── Single Office Businesses ──────────────────────────────────────────────
    {
        "name": "Single Office Businesses",
        "slug": "single-office-monthly",
        "description": (
            "Built for single office property businesses handling regular enquiries. "
            "Recommended for single office agencies, boutique real estate agencies, "
            "property investment firms, and property advisory businesses."
        ),
        "billing_interval": BillingInterval.MONTHLY,
        "price_aud_cents": 50_000,  # AUD 500/month
        "price_usd_cents": 33_000,  # USD 330/month
        "is_public": True,
        "sort_order": 3,
        "limits": DEFAULT_LIMITS,
    },
    {
        "name": "Single Office Businesses Annual",
        "slug": "single-office-annual",
        "description": ("Single Office Businesses plan billed annually. Save 20%."),
        "billing_interval": BillingInterval.ANNUAL,
        "price_aud_cents": 480_000,  # AUD 500 * 12 * 0.8 = 4800/year
        "price_usd_cents": 316_800,
        "is_public": True,
        "sort_order": 4,
        "limits": DEFAULT_LIMITS,
    },
    # ── Regional Property Businesses ──────────────────────────────────────────
    {
        "name": "Regional Property Businesses",
        "slug": "regional-property-monthly",
        "description": (
            "Designed for larger property organisations and higher volume developments. "
            "Recommended for regional agencies with multiple offices, apartment developments "
            "with 20+ units, medium sized residential builders, and large land development projects."
        ),
        "billing_interval": BillingInterval.MONTHLY,
        "price_aud_cents": 75_000,  # AUD 750/month
        "price_usd_cents": 50_000,  # USD 500/month
        "is_public": True,
        "sort_order": 5,
        "limits": DEFAULT_LIMITS,
    },
    {
        "name": "Regional Property Businesses Annual",
        "slug": "regional-property-annual",
        "description": ("Regional Property Businesses plan billed annually. Save 20%."),
        "billing_interval": BillingInterval.ANNUAL,
        "price_aud_cents": 720_000,  # AUD 750 * 12 * 0.8 = 7200/year
        "price_usd_cents": 480_000,
        "is_public": True,
        "sort_order": 6,
        "limits": DEFAULT_LIMITS,
    },
    # ── Major Builders and Developers ─────────────────────────────────────────
    {
        "name": "Major Builders and Developers",
        "slug": "major-builders-monthly",
        "description": (
            "Built for large scale property organisations and high traffic development platforms. "
            "Recommended for statewide agencies, major residential builders, "
            "large apartment developers, and large scale development websites."
        ),
        "billing_interval": BillingInterval.MONTHLY,
        "price_aud_cents": 100_000,  # AUD 1000/month
        "price_usd_cents": 66_000,  # USD 660/month
        "is_public": True,
        "sort_order": 7,
        "limits": DEFAULT_LIMITS,
    },
    {
        "name": "Major Builders and Developers Annual",
        "slug": "major-builders-annual",
        "description": (
            "Major Builders and Developers plan billed annually. Save 20%."
        ),
        "billing_interval": BillingInterval.ANNUAL,
        "price_aud_cents": 960_000,  # AUD 1000 * 12 * 0.8 = 9600/year
        "price_usd_cents": 633_600,
        "is_public": True,
        "sort_order": 8,
        "limits": DEFAULT_LIMITS,
    },
]

ADDONS = [
    # ── Existing addons ───────────────────────────────────────────────────────
    {
        "name": "Extra Team Member",
        "slug": "extra-users",
        "description": "Add 1 additional team member seat to your plan.",
        "type": AddonType.EXTRA_USERS,
        "price_aud_cents": 1_500,  # AUD 15/month per seat
        "price_usd_cents": 1_000,
        "config": {"grants_per_unit": {"max_users": 1}},
    },
    {
        "name": "Extra Conversations",
        "slug": "extra-conversations",
        "description": "Add 250 extra conversations per month.",
        "type": AddonType.EXTRA_CONVERSATIONS,
        "price_aud_cents": 1_500,  # AUD 15/month per 250 conversations
        "price_usd_cents": 1_000,
        "config": {"grants_per_unit": {"max_conversations_per_month": 250}},
    },
    {
        "name": "Extra Storage",
        "slug": "extra-storage",
        "description": "Add 5GB (5,000MB) extra document storage.",
        "type": AddonType.EXTRA_STORAGE,
        "price_aud_cents": 1_000,  # AUD 10/month per 5GB
        "price_usd_cents": 700,
        "config": {"grants_per_unit": {"max_storage_mb": 5_000}},
    },
    {
        "name": "Premium Widget",
        "slug": "premium-widget",
        "description": "Unlock premium widget themes and advanced customisation.",
        "type": AddonType.PREMIUM_WIDGET,
        "price_aud_cents": 2_900,  # AUD 29/month
        "price_usd_cents": 1_900,
        "config": {"grants_per_unit": {"premium_widget": 1}},
    },
    # ── New addons (all AUD 15/month) ─────────────────────────────────────────
    {
        "name": "Extra Chatbot",
        "slug": "extra-chatbots",
        "description": "Add 1 additional chatbot to your plan.",
        "type": AddonType.EXTRA_CHATBOTS,
        "price_aud_cents": 1_500,  # AUD 15/month
        "price_usd_cents": 1_000,
        "config": {"grants_per_unit": {"max_chatbots": 1}},
    },
    {
        "name": "Extra 1M Tokens",
        "slug": "extra-tokens",
        "description": "Add 1,000,000 extra tokens per month.",
        "type": AddonType.EXTRA_TOKENS,
        "price_aud_cents": 1_500,  # AUD 15/month per 1M tokens
        "price_usd_cents": 1_000,
        "config": {"grants_per_unit": {"max_tokens_per_month": 1_000_000}},
    },
    {
        "name": "Custom Banner & Poster",
        "slug": "custom-banner",
        "description": "Unlock custom banner and poster upload for your chatbot.",
        "type": AddonType.CUSTOM_BANNER,
        "price_aud_cents": 1_500,  # AUD 15/month
        "price_usd_cents": 1_000,
        "config": {"grants_per_unit": {"custom_banner": 1}},
    },
    {
        "name": "Extra Ribbon Messages",
        "slug": "extra-ribbon-messages",
        "description": "Add 3 extra ribbon message slots (rotating popup messages).",
        "type": AddonType.EXTRA_RIBBON_MESSAGES,
        "price_aud_cents": 1_500,  # AUD 15/month per 3 slots
        "price_usd_cents": 1_000,
        "config": {"grants_per_unit": {"max_ribbon_messages": 3}},
    },
    {
        "name": "Extra Pages",
        "slug": "extra-pages",
        "description": "Add 50 extra crawlable pages to your knowledge base.",
        "type": AddonType.EXTRA_PAGES,
        "price_aud_cents": 1_500,  # AUD 15/month per 50 pages
        "price_usd_cents": 1_000,
        "config": {"grants_per_unit": {"max_pages_crawled": 50}},
    },
]


async def seed_plans_and_addons(db: AsyncSession) -> None:
    """
    Idempotent — skips rows where slug already exists.
    Safe to run multiple times.
    """
    print("── Seeding plans ────────────────────────────────")
    for data in PLANS:
        existing = await db.execute(select(Plan).where(Plan.slug == data["slug"]))
        if existing.scalar_one_or_none():
            print(f"  ✓ skip  '{data['slug']}' (already exists)")
            continue
        plan = Plan(**data)
        db.add(plan)
        print(f"  + add   '{data['slug']}'")

    print("── Seeding addons ───────────────────────────────")
    for data in ADDONS:
        existing = await db.execute(select(Addon).where(Addon.slug == data["slug"]))
        if existing.scalar_one_or_none():
            print(f"  ✓ skip  '{data['slug']}' (already exists)")
            continue
        addon = Addon(**data)
        db.add(addon)
        print(f"  + add   '{data['slug']}'")

    await db.commit()
    print("── Seeding complete ─────────────────────────────")
