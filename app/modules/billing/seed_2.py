# app/modules/billing/seed_2.py
"""
Updated plan pricing + Enterprise plan + full addon list.

This file UPSERTS — it creates plans/addons that don't exist yet and
updates name, description, and prices for slugs that already exist.
Run once after the pricing change goes live.

Usage:
    from app.modules.billing.seed_2 import seed_v2
    await seed_v2(db)
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.modules.billing.models import Plan, Addon
from app.core.enums import BillingInterval, AddonType


# =============================================================================
# DEFAULT LIMITS — applied to lower tiers (Project Developments, Single Office)
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

# Premium-tier limits: same as default, plus Premium AI chat model entitlement.
# Tenants on these plans can set their chatbot model to gpt-4.1 without
# purchasing the EXTRA_PREMIUM_MODEL add-on separately.
PREMIUM_LIMITS = {
    **DEFAULT_LIMITS,
    "includes_premium_model": 1,
}

# =============================================================================
# PLANS
# =============================================================================
PLANS = [
    # ── Project Developments — Monthly ───────────────────────────────────────
    {
        "name": "Project Developments",
        "slug": "project-developments-monthly",
        "description": (
            "Designed for single property development websites with focused traffic. "
            "Recommended for land estates with a single website, boutique apartment "
            "developments under 20 units, small project marketing websites, and "
            "individual development landing pages."
        ),
        "billing_interval": BillingInterval.MONTHLY,
        "price_aud_cents": 40_000,   # AUD 400/month
        "price_usd_cents": 26_700,   # USD 267/month
        "is_public": True,
        "sort_order": 1,
        "limits": DEFAULT_LIMITS,
    },
    # ── Project Developments — Annual ─────────────────────────────────────────
    {
        "name": "Project Developments Annual",
        "slug": "project-developments-annual",
        "description": (
            "Project Developments plan billed annually. Save 25%. "
            "Designed for single property development websites with focused traffic."
        ),
        "billing_interval": BillingInterval.ANNUAL,
        "price_aud_cents": 360_000,  # AUD 300/month × 12 = 3,600/year
        "price_usd_cents": 240_000,  # USD 240/month × 12 = 2,880/year
        "is_public": True,
        "sort_order": 2,
        "limits": DEFAULT_LIMITS,
    },
    # ── Single Office Businesses — Monthly ────────────────────────────────────
    {
        "name": "Single Office Businesses",
        "slug": "single-office-monthly",
        "description": (
            "Built for single office property businesses handling regular enquiries. "
            "Recommended for single office real estate agencies, boutique real estate "
            "agencies, property investment firms, and property advisory businesses."
        ),
        "billing_interval": BillingInterval.MONTHLY,
        "price_aud_cents": 65_000,   # AUD 650/month
        "price_usd_cents": 43_300,   # USD 433/month
        "is_public": True,
        "sort_order": 3,
        "limits": DEFAULT_LIMITS,
    },
    # ── Single Office Businesses — Annual ─────────────────────────────────────
    {
        "name": "Single Office Businesses Annual",
        "slug": "single-office-annual",
        "description": (
            "Single Office Businesses plan billed annually. Save ~23%. "
            "Built for single office property businesses handling regular enquiries."
        ),
        "billing_interval": BillingInterval.ANNUAL,
        "price_aud_cents": 600_000,  # AUD 500/month × 12 = 6,000/year
        "price_usd_cents": 400_000,  # USD 333/month × 12 = 4,000/year
        "is_public": True,
        "sort_order": 4,
        "limits": DEFAULT_LIMITS,
    },
    # ── Regional Property Businesses — Monthly ────────────────────────────────
    {
        "name": "Regional Property Businesses",
        "slug": "regional-property-monthly",
        "description": (
            "Designed for larger property organisations and higher volume developments. "
            "Recommended for regional real estate agencies with multiple offices, "
            "apartment developments with 20+ units, medium sized residential builders, "
            "and large land development projects."
        ),
        "billing_interval": BillingInterval.MONTHLY,
        "price_aud_cents": 90_000,   # AUD 900/month
        "price_usd_cents": 60_000,   # USD 600/month
        "is_public": True,
        "sort_order": 5,
        "limits": PREMIUM_LIMITS,
    },
    # ── Regional Property Businesses — Annual ─────────────────────────────────
    {
        "name": "Regional Property Businesses Annual",
        "slug": "regional-property-annual",
        "description": (
            "Regional Property Businesses plan billed annually. Save ~17%. "
            "Designed for larger property organisations and higher volume developments."
        ),
        "billing_interval": BillingInterval.ANNUAL,
        "price_aud_cents": 900_000,  # AUD 750/month × 12 = 9,000/year
        "price_usd_cents": 600_000,  # USD 500/month × 12 = 6,000/year
        "is_public": True,
        "sort_order": 6,
        "limits": PREMIUM_LIMITS,
    },
    # ── Major Builders and Developers — Monthly ───────────────────────────────
    {
        "name": "Major Builders and Developers",
        "slug": "major-builders-monthly",
        "description": (
            "Built for large scale property organisations and high traffic development "
            "platforms. Recommended for statewide real estate agencies, major residential "
            "builders, large apartment developers, and large scale development websites."
        ),
        "billing_interval": BillingInterval.MONTHLY,
        "price_aud_cents": 120_000,  # AUD 1,200/month
        "price_usd_cents": 80_000,   # USD 800/month
        "is_public": True,
        "sort_order": 7,
        "limits": PREMIUM_LIMITS,
    },
    # ── Major Builders and Developers — Annual ────────────────────────────────
    {
        "name": "Major Builders and Developers Annual",
        "slug": "major-builders-annual",
        "description": (
            "Major Builders and Developers plan billed annually. Save ~17%. "
            "Built for large scale property organisations and high traffic development platforms."
        ),
        "billing_interval": BillingInterval.ANNUAL,
        "price_aud_cents": 1_200_000,  # AUD 1,000/month × 12 = 12,000/year
        "price_usd_cents": 800_000,    # USD 667/month × 12 = 8,000/year
        "is_public": True,
        "sort_order": 8,
        "limits": PREMIUM_LIMITS,
    },
    # ── Enterprise — Custom ───────────────────────────────────────────────────
    {
        "name": "Enterprise",
        "slug": "enterprise",
        "description": (
            "Custom deployment for organisations operating across multiple brands, "
            "projects, or national networks. Recommended for national real estate "
            "franchises, national builders, national property developers, and property "
            "portals and marketplaces. Includes multi website deployments and custom "
            "integrations and onboarding."
        ),
        "billing_interval": BillingInterval.MONTHLY,
        "price_aud_cents": 0,   # Custom pricing — set manually per tenant
        "price_usd_cents": 0,
        "is_public": False,     # Hidden from public plan list; assigned by admins
        "sort_order": 9,
        "limits": PREMIUM_LIMITS,
    },
]

# =============================================================================
# ADDONS — unchanged
# =============================================================================
ADDONS = [
    {
        "name": "Extra Team Member",
        "slug": "extra-users",
        "description": "Add 1 additional team member seat to your plan.",
        "type": AddonType.EXTRA_USERS,
        "price_aud_cents": 1_500,
        "price_usd_cents": 1_000,
        "config": {"grants_per_unit": {"max_users": 1}},
    },
    {
        "name": "Extra Conversations",
        "slug": "extra-conversations",
        "description": "Add 250 extra conversations per month.",
        "type": AddonType.EXTRA_CONVERSATIONS,
        "price_aud_cents": 1_500,
        "price_usd_cents": 1_000,
        "config": {"grants_per_unit": {"max_conversations_per_month": 250}},
    },
    {
        "name": "Extra Storage",
        "slug": "extra-storage",
        "description": "Add 5GB (5,000MB) extra document storage.",
        "type": AddonType.EXTRA_STORAGE,
        "price_aud_cents": 1_000,
        "price_usd_cents": 700,
        "config": {"grants_per_unit": {"max_storage_mb": 5_000}},
    },
    {
        "name": "Premium Widget",
        "slug": "premium-widget",
        "description": "Unlock premium widget themes and advanced customisation.",
        "type": AddonType.PREMIUM_WIDGET,
        "price_aud_cents": 2_900,
        "price_usd_cents": 1_900,
        "config": {"grants_per_unit": {"premium_widget": 1}},
    },
    {
        "name": "Extra Chatbot",
        "slug": "extra-chatbots",
        "description": "Add 1 additional chatbot to your plan.",
        "type": AddonType.EXTRA_CHATBOTS,
        "price_aud_cents": 1_500,
        "price_usd_cents": 1_000,
        "config": {"grants_per_unit": {"max_chatbots": 1}},
    },
    {
        "name": "Extra 1M Tokens",
        "slug": "extra-tokens",
        "description": "Add 1,000,000 extra tokens per month.",
        "type": AddonType.EXTRA_TOKENS,
        "price_aud_cents": 1_500,
        "price_usd_cents": 1_000,
        "config": {"grants_per_unit": {"max_tokens_per_month": 1_000_000}},
    },
    {
        "name": "Branded Banner",
        "slug": "custom-banner",
        "description": (
            "Inject a custom hero banner directly into your chatbot. "
            "Makes every conversation unmistakably yours."
        ),
        "type": AddonType.CUSTOM_BANNER,
        "price_aud_cents": 1_500,
        "price_usd_cents": 1_000,
        "config": {"grants_per_unit": {"custom_banner": 1}},
    },
    {
        "name": "Extra Ribbon Messages",
        "slug": "extra-ribbon-messages",
        "description": "Add 3 extra ribbon message slots (rotating popup messages).",
        "type": AddonType.EXTRA_RIBBON_MESSAGES,
        "price_aud_cents": 1_500,
        "price_usd_cents": 1_000,
        "config": {"grants_per_unit": {"max_ribbon_messages": 3}},
    },
    {
        "name": "Extra Pages",
        "slug": "extra-pages",
        "description": "Add 50 extra crawlable pages to your knowledge base.",
        "type": AddonType.EXTRA_PAGES,
        "price_aud_cents": 1_500,
        "price_usd_cents": 1_000,
        "config": {"grants_per_unit": {"max_pages_crawled": 50}},
    },
    {
        "name": "Premium AI",
        "slug": "premium-ai",
        "description": (
            "Upgrade your chatbot's chat model from the standard tier to gpt-4.1 "
            "for more nuanced conversation quality. Applies to any chatbot you "
            "set to a premium model in the chatbot settings."
        ),
        "type": AddonType.EXTRA_PREMIUM_MODEL,
        "price_aud_cents": 2_200,   # ~AUD 22 / month
        "price_usd_cents": 1_500,   # ~USD 15 / month
        "config": {"grants_per_unit": {"premium_model": 1}},
    },
]


# =============================================================================
# SEED FUNCTION — upsert (create or update) + Stripe push
# =============================================================================
async def seed_v2(db: AsyncSession) -> None:
    """
    Idempotent upsert:
      - If a plan/addon slug already exists → update name, description, prices,
        limits (plans), config (addons).
      - If it does not exist → insert it.
      - After commit, push any plan/addon missing a Stripe price ID to Stripe.

    Safe to run multiple times. Re-running won't duplicate Stripe products
    because we only call Stripe when stripe_*_price_id is null.
    """
    # Local imports to avoid heavy service-layer imports at module load time.
    from app.modules.billing.service import (
        _create_stripe_product_and_price,
        _create_stripe_product_and_price_for_addon,
        _stripe_ready,
    )

    print("── Seeding plans (v2) ───────────────────────────")
    for data in PLANS:
        result = await db.execute(select(Plan).where(Plan.slug == data["slug"]))
        plan = result.scalar_one_or_none()
        if plan:
            plan.name             = data["name"]
            plan.description      = data.get("description")
            plan.price_aud_cents  = data["price_aud_cents"]
            plan.price_usd_cents  = data["price_usd_cents"]
            plan.is_public        = data.get("is_public", True)
            plan.sort_order       = data.get("sort_order", 0)
            # Refresh limits so new keys (e.g. includes_premium_model) propagate.
            plan.limits           = data.get("limits", {})
            print(f"  ~ update '{data['slug']}'")
        else:
            db.add(Plan(**data))
            print(f"  + add    '{data['slug']}'")

    print("── Seeding addons (v2) ──────────────────────────")
    for data in ADDONS:
        result = await db.execute(select(Addon).where(Addon.slug == data["slug"]))
        addon = result.scalar_one_or_none()
        if addon:
            addon.name            = data["name"]
            addon.description     = data.get("description")
            addon.price_aud_cents = data["price_aud_cents"]
            addon.price_usd_cents = data["price_usd_cents"]
            # Refresh config so grants_per_unit changes propagate.
            addon.config          = data.get("config", {})
            print(f"  ~ update '{data['slug']}'")
        else:
            db.add(Addon(**data))
            print(f"  + add    '{data['slug']}'")

    await db.commit()

    # ── Stripe sync ──────────────────────────────────────────────────────────
    # Push every plan / addon that still has no Stripe price ID. Skips items
    # already synced (so this is safe to re-run) and zero-price items (e.g.
    # Enterprise custom plan).
    if _stripe_ready():
        print("── Pushing missing plans/addons to Stripe ───────")
        all_plans = (await db.execute(select(Plan))).scalars().all()
        for plan in all_plans:
            already_synced = (
                plan.stripe_monthly_price_id is not None
                or plan.stripe_annual_price_id is not None
            )
            if already_synced or plan.price_usd_cents <= 0:
                continue
            print(f"  → stripe push plan '{plan.slug}'")
            _create_stripe_product_and_price(plan)

        all_addons = (await db.execute(select(Addon))).scalars().all()
        for addon in all_addons:
            if addon.stripe_price_id is not None or addon.price_usd_cents <= 0:
                continue
            print(f"  → stripe push addon '{addon.slug}'")
            _create_stripe_product_and_price_for_addon(addon)

        await db.commit()
        print("── Stripe push complete ─────────────────────────")
    else:
        print("── Stripe not configured — skipping Stripe push ──")

    print("── Seeding v2 complete ──────────────────────────")
