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
    logger.debug("[users] get_current_user_profile user=%s", current_user.public_id)
    user = await repo.get_user_by_id(db, id=current_user.id)

    if not user:
        logger.warning("[users] get_current_user_profile user not found id=%s", current_user.id)
        raise UserNotFoundError()

    logger.debug("[users] get_current_user_profile fetched public_id=%s", user.public_id)
    return schemas.UserProfileResponse.model_validate(user)