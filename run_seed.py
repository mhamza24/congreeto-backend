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
from app.modules.chatbot.seed_personalities import seed_personalities


async def main() -> None:
    async with AsyncSessionLocal() as db:
        await seed_plans_and_addons(db)
        await seed_personalities(db)


if __name__ == "__main__":
    asyncio.run(main())
