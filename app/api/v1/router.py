from fastapi import APIRouter
from app.modules.chat.api import router as chat_router
from app.modules.server.api import router as server_router
from app.modules.chatbot.api import router as chatbot_router
from app.modules.campaigns.api import router as campaigns_router
from app.modules.dashboard.api import router as dashboard_router
from app.modules.inquiries.api import router as inquiries_router
from app.modules.auth.api import router as auth_router
from app.modules.tenants.api import router as tenants_router
from app.modules.users.api import router as users_router
from app.modules.billing.api import router as billing_router
from app.modules.listings.api import router as listings_router
from app.modules.audit.api import router as audit_router

router = APIRouter()

router.include_router(chat_router)
router.include_router(server_router)
router.include_router(chatbot_router)
router.include_router(campaigns_router)
router.include_router(dashboard_router)
router.include_router(inquiries_router)
router.include_router(auth_router)
router.include_router(tenants_router)
router.include_router(users_router)
router.include_router(billing_router)
router.include_router(listings_router)
router.include_router(audit_router)
