import hashlib
import logging
import secrets

import bcrypt

from app.config.settings import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

IDENTITY_HASH_SALT   = settings.IDENTITY_HASH_SALT
PASSWORD_HASH_PEPPER = settings.PASSWORD_HASH_PEPPER
PASSWORD_HASH_ROUNDS = settings.PASSWORD_HASH_ROUND    
OTP_HASH_SALT        = settings.OTP_HASH_SALT


# ── Identity hash (email → SHA-256) ──────────────────────────────────────────

def hash_identity(value: str) -> str:
    """
    SHA-256 of salted+lowercased value.
    Used for email_hash on User — enables chatbot visitor re-identification
    without exposing the raw email in queries or JS.
    """
    salted = f"{IDENTITY_HASH_SALT}{value.lower().strip()}"
    return hashlib.sha256(salted.encode()).hexdigest()


# ── Password hashing (bcrypt + pepper) ───────────────────────────────────────

def _apply_pepper(plain: str) -> str:
    """
    HMAC-SHA256 the plain password with the pepper before bcrypt.
    Pepper lives in env/vault — NOT in the DB.
    Even a full DB dump cannot crack the hash without the pepper.
    Must be applied identically in both hash and verify.
    """
    return hashlib.pbkdf2_hmac(
        "sha256",
        plain.encode(),
        PASSWORD_HASH_PEPPER.encode(),
        iterations=1,         # pepper step only — bcrypt does the real stretching
    ).hex()


def hash_password(plain: str) -> str:
    """
    Pipeline: plain → pepper (HMAC-SHA256) → bcrypt (cost = PASSWORD_HASH_ROUND)

    PASSWORD_HASH_ROUND in .env:
        10 → ~100ms  (minimum acceptable)
        12 → ~400ms  (production standard)
        14 → ~1.5s   (high security)
    """
    peppered = _apply_pepper(plain)
    return bcrypt.hashpw(
        peppered.encode(),
        bcrypt.gensalt(rounds=PASSWORD_HASH_ROUNDS),   # ✅ int, not the pepper string
    ).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """
    Apply identical pepper pipeline before checking against stored bcrypt hash.
    Constant-time — never raises, returns False on any malformed input.
    """
    try:
        peppered = _apply_pepper(plain)                # ✅ same pipeline as hash_password
        return bcrypt.checkpw(peppered.encode(), hashed.encode())
    except Exception:
        logger.warning("Password verification failed — malformed hash or input.")
        return False


# ── OTP ───────────────────────────────────────────────────────────────────────

def generate_otp(length: int = 6) -> str:
    """
    Cryptographically secure numeric OTP.
    secrets.randbelow(10) gives a random digit 0-9.
    OTP_HASH_SALT is used during hashing — not here during generation.
    """
    return "".join(str(secrets.randbelow(10)) for _ in range(length))  # ✅ 10, not the salt


def hash_otp(raw_otp: str) -> str:
    """
    SHA-256 of salted OTP.
    Salt scopes the hash to this platform — prevents rainbow table attacks
    on the small 6-digit OTP space (only 1,000,000 combinations).
    Only the hash is stored in DB — raw code lives in the email only.
    """
    salted = f"{OTP_HASH_SALT}{raw_otp}"               # ✅ salt applied here
    return hashlib.sha256(salted.encode()).hexdigest()


def verify_otp(raw_otp: str, stored_hash: str) -> bool:
    """
    Constant-time comparison for OTP verification.
    secrets.compare_digest prevents timing attacks on the hash comparison.
    """
    return secrets.compare_digest(hash_otp(raw_otp), stored_hash)