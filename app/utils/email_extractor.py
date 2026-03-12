import re
from enum import Enum

# ── Compiled once at module level ────────────────────────────

_EMAIL_RE = re.compile(
    r"""
    (?<![a-zA-Z0-9._%+\-])
    (
        [a-zA-Z0-9._%+\-]+
        @
        [a-zA-Z0-9\-]+
        (?:\.[a-zA-Z0-9\-]+)*
        \.
        [a-zA-Z]{2,}
    )
    (?![a-zA-Z0-9._%+\-])
    """,
    re.VERBOSE | re.IGNORECASE,
)

# International phone — covers virtually all formats worldwide
_PHONE_RE = re.compile(
    r"""
    (?<!\d)
    (
        (?:
            \+\d{1,3}          # +1, +44, +61, +971, +92 etc
            [\s\-\.]?
        )?
        (?:
            \(?\d{1,4}\)?      # optional area code with or without parens
            [\s\-\.]?
        )?
        \d{2,4}                # first number group
        [\s\-\.]?
        \d{2,4}                # second number group
        [\s\-\.]?
        \d{2,4}                # third number group
        (?:[\s\-\.]?\d{1,4})? # optional extension
    )
    (?!\d)
    """,
    re.VERBOSE,
)

_INVALID_EMAIL_PATTERNS = [
    re.compile(
        r"\.(png|jpg|jpeg|gif|svg|webp|pdf|doc|docx|zip|exe)$", re.IGNORECASE),
]

_DISPOSABLE_DOMAINS = {
    "mailinator.com", "guerrillamail.com", "trashmail.com",
    "tempmail.com", "throwaway.email", "yopmail.com",
}

# Minimum digits a string must have to be a real phone number
_PHONE_MIN_DIGITS = 7
# Maximum digits — anything above is likely not a phone number
_PHONE_MAX_DIGITS = 15  # E.164 international standard max


class IdentityType(str, Enum):
    email = "email"
    phone = "phone"


def extract_and_validate_identity(
    message: str,
) -> tuple[str | None, IdentityType | None, bool]:
    """
    Extracts and validates the first email or phone found in a message.
    Works globally — not tied to any specific country format.
    Email takes priority over phone.

    Returns (value, type, is_valid):

      (None,         None,               False) → nothing found
      ("x@y.com",    IdentityType.email, True)  → valid email
      ("x@y.com",    IdentityType.email, False) → email found, failed validation
      ("+1234567890", IdentityType.phone, True)  → valid phone
      ("+1234567890", IdentityType.phone, False) → phone found, failed validation
    """
    if not message or not isinstance(message, str):
        return None, None, False

    # ── Email first (higher priority) ────────────────────────
    email_match = _EMAIL_RE.search(message)
    if email_match:
        email = email_match.group(1).lower().strip()

        if email.count("@") != 1:
            return email, IdentityType.email, False

        local, domain = email.split("@")

        if len(local) > 64:
            return email, IdentityType.email, False

        if len(domain) > 255:
            return email, IdentityType.email, False

        if local.startswith(".") or local.endswith("."):
            return email, IdentityType.email, False

        if ".." in local:
            return email, IdentityType.email, False

        if "." not in domain:
            return email, IdentityType.email, False

        tld = domain.rsplit(".", 1)[-1]
        if len(tld) < 2:
            return email, IdentityType.email, False

        for pattern in _INVALID_EMAIL_PATTERNS:
            if pattern.search(domain):
                return email, IdentityType.email, False

        if domain in _DISPOSABLE_DOMAINS:
            return email, IdentityType.email, False

        return email, IdentityType.email, True

    # ── Phone second ─────────────────────────────────────────
    phone_match = _PHONE_RE.search(message)
    if phone_match:
        raw = phone_match.group(1)

        # Normalise — strip formatting for consistent hashing
        # keeps + prefix if present (important for international)
        has_plus = raw.lstrip().startswith("+")
        digits = re.sub(r"\D", "", raw)

        # Digit count validation — E.164 standard (7–15 digits)
        if not (_PHONE_MIN_DIGITS <= len(digits) <= _PHONE_MAX_DIGITS):
            return raw.strip(), IdentityType.phone, False

        # Reconstruct clean normalised form
        normalised = f"+{digits}" if has_plus else digits

        return normalised, IdentityType.phone, True

    return None, None, False
