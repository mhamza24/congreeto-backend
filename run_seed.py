"""
Run DB seed for plans, addons, and prompt personalities.
Usage: python run_seed.py
"""
import asyncio

# Import all models so SQLAlchemy can resolve all relationships before queries run
import app.modules.users.models          # noqa: F401
import app.modules.auth.models           # noqa: F401
import app.modules.tenants.models        # noqa: F401
import app.modules.models.tenant_user    # noqa: F401
import app.modules.models.otp            # noqa: F401
import app.modules.billing.models        # noqa: F401
import app.modules.chatbot.models        # noqa: F401
import app.modules.campaigns.models      # noqa: F401
import app.modules.chat.models           # noqa: F401

from app.core.database import AsyncSessionLocal
from app.modules.billing.seed import seed_plans_and_addons
from app.modules.billing.seed_2 import seed_v2
from app.modules.chatbot.seed_personalities import seed_personalities


async def main() -> None:
    async with AsyncSessionLocal() as db:
        await seed_plans_and_addons(db)
        # seed_v2 upserts updated plan pricing, the Premium AI add-on, and the
        # includes_premium_model entitlement on Plan 3+ tiers. Safe to re-run.
        await seed_v2(db)
        await seed_personalities(db)


if __name__ == "__main__":
    asyncio.run(main())
