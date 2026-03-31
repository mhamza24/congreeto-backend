import hashlib
import logging
import secrets

import bcrypt

from app.config.settings import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

IDENTITY_HASH_SALT = settings.IDENTITY_HASH_SALT
PASSWORD_HASH_SALT=settings.PASSWORD_HASH_SALT
OPT_HASH_SALT=settings.OTP_HASH_SALT


# ── Identity hash (email → SHA-256) ──────────────────────────────────────────

def hash_identity(value: str) -> str:
    """
    SHA-256 of salted+lowercased value.
    Used for email_hash on User — enables chatbot visitor re-identification
    without exposing the raw email in queries or JS.
    """
    salted = f"{IDENTITY_HASH_SALT}{value.lower().strip()}"
    return hashlib.sha256(salted.encode()).hexdigest()


# ── Password hashing (bcrypt) ─────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    """
    Hashes a plain-text password with bcrypt.
    bcrypt automatically generates and embeds a unique salt per hash —
    no manual salt management needed.
    Cost factor 12 is the production standard (adjust up as hardware improves).
    """
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=PASSWORD_HASH_SALT)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """
    Constant-time comparison against a bcrypt hash.
    Always call this — never compare password strings directly.
    Returns False (never raises) on malformed hash, to prevent timing attacks
    from leaking whether a user exists.
    """
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        logger.warning("bcrypt verification failed — malformed hash in DB.")
        return False


# ── OTP ───────────────────────────────────────────────────────────────────────

def generate_otp(length: int = 6) -> str:
    """
    Cryptographically secure numeric OTP.
    secrets.randbelow is CSPRNG-backed — never use random.randint for OTPs.
    """
    return "".join(str(secrets.randbelow(OPT_HASH_SALT)) for _ in range(length))


def hash_otp(raw_otp: str) -> str:
    """
    SHA-256 of the raw OTP code.
    Only the hash is stored in DB — raw code lives in the email only.
    """
    return hashlib.sha256(raw_otp.encode()).hexdigest()


def verify_otp(raw_otp: str, stored_hash: str) -> bool:
    """
    Constant-time comparison for OTP verification.
    secrets.compare_digest prevents timing attacks on the hash comparison.
    """
    return secrets.compare_digest(hash_otp(raw_otp), stored_hash)