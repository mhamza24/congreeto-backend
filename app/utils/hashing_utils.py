import hashlib
import logging
from app.config.settings import get_settings



settings = get_settings()
logger = logging.getLogger(__name__)


IDENTITY_HASH_SALT=settings.IDENTITY_HASH_SALT

def hash_identity(value: str) -> str:
    salted = f"{IDENTITY_HASH_SALT}{value.lower().strip()}"
    return hashlib.sha256(salted.encode()).hexdigest()
