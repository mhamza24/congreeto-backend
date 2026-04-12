import logging

from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import UserNotFoundError
from app.modules.users import repository as repo, schemas
from app.modules.users.models import User

logger = logging.getLogger(__name__)

async def get_current_user_profile(
    db: AsyncSession,
    *,
    current_user: User,
) -> schemas.UserProfileResponse:
    """
    Fetch the full profile of the currently authenticated user.
    """
    user = await repo.get_user_by_id(db, id=current_user.id)

    if not user:
        raise UserNotFoundError()

    return schemas.UserProfileResponse.model_validate(user)