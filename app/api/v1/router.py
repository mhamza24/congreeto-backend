from fastapi import APIRouter
from app.modules.chat.api import router as chat_router
from app.modules.server.api import router as server_router
from app.modules.onboarding.api import router as embedding_router
from app.modules.dashboard.api import router as dashboard_router
from app.modules.inquiries.api import router as inquiries_router

router = APIRouter()

router.include_router(chat_router)
router.include_router(server_router)
router.include_router(embedding_router)
router.include_router(dashboard_router)
router.include_router(inquiries_router)