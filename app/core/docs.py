import secrets
from fastapi import Depends, HTTPException, status
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from app.config.settings import get_settings

settings = get_settings()
basic_auth = HTTPBasic()


def verify_docs_credentials(credentials: HTTPBasicCredentials = Depends(basic_auth)):
    """Protect docs with basic auth in non-production environments."""
    correct_username = secrets.compare_digest(
        credentials.username.encode(),
        settings.DOCS_USERNAME.encode(),
    )
    correct_password = secrets.compare_digest(
        credentials.password.encode(),
        settings.DOCS_PASSWORD.encode(),
    )
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials.",
            headers={"WWW-Authenticate": "Basic"},
        )
