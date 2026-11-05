"""Database and authentication dependencies.

Separated from main.py to avoid circular imports with routers.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.models import Organization, User
from app.config import SessionLocal, JWT_SECRET

bearer = HTTPBearer(auto_error=False)


def get_session():
    """Database session dependency."""
    with SessionLocal() as session:
        yield session


# Keep the dependency names used by the catalog routers while sharing the
# same session lifecycle as the mobile endpoints.
get_db = get_session


def token_for(user: User) -> str:
    """Generate JWT token for user."""
    expires = datetime.now(timezone.utc) + timedelta(days=30)
    return jwt.encode(
        {"sub": str(user.id), "org": str(user.organization_id), "role": user.role, "exp": expires},
        JWT_SECRET,
        algorithm="HS256",
    )


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: Session = Depends(get_session),
) -> User:
    """Get current authenticated user from JWT token."""
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=["HS256"])
        user_id = UUID(payload["sub"])
        organization_id = UUID(payload["org"])
    except (jwt.PyJWTError, ValueError, KeyError) as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from error
    user = session.get(User, user_id)
    if user is None or not user.active or user.organization_id != organization_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session revoked")
    return user


def get_current_organization(
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> Organization:
    """Resolve the authenticated tenant without accepting a client-supplied ID."""
    organization = session.get(Organization, user.organization_id)
    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Organization unavailable",
        )
    return organization
