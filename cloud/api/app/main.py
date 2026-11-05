"""API cloud inicial de Doccione.

Es independiente de Studio para poder desplegarse en un VPS. Cada petición
autenticada se restringe a una organización, evitando mezclar datos entre
negocios que usan la plataforma.
"""
from __future__ import annotations

import os
from uuid import UUID, uuid4

import jwt
from fastapi import Depends, FastAPI, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from pwdlib import PasswordHash
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base, Organization, User
from app.config import DATABASE_URL, JWT_SECRET, BOOTSTRAP_TOKEN, SessionLocal
from app.dependencies import token_for, get_session, current_user
from app.routers import orders, jobs, production_history, sync, products, product_variants, price_lists, price_rules

password_hash = PasswordHash.recommended()


class BootstrapRequest(BaseModel):
    organization_name: str = Field(min_length=2, max_length=160)
    organization_slug: str = Field(pattern=r"^[a-z0-9-]{3,80}$")
    owner_email: EmailStr
    owner_password: str = Field(min_length=12, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


app = FastAPI(title="Doccione Cloud API", version="0.1.0", docs_url=None, redoc_url=None)

# Include routers
app.include_router(orders.router)
app.include_router(jobs.router)
app.include_router(production_history.router)
app.include_router(sync.router)
app.include_router(products.router)
app.include_router(product_variants.router)
app.include_router(price_lists.router)
app.include_router(price_rules.router)


@app.on_event("startup")
def create_schema() -> None:
    # Las tablas se crean mediante Alembic migraciones.
    # Este evento se mantiene para compatibilidad durante desarrollo.
    pass


@app.get("/api/v1/mobile/health")
def health() -> dict[str, object]:
    return {"status": "ok", "service": "doccione-studio", "api_version": "v1", "mobile_api": True, "deployment": "cloud"}


@app.post("/api/v1/platform/bootstrap", status_code=status.HTTP_201_CREATED)
def bootstrap(payload: BootstrapRequest, request: Request, session: Session = Depends(get_session)) -> dict[str, str]:
    if request.headers.get("X-Bootstrap-Token", "") != BOOTSTRAP_TOKEN:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bootstrap token")
    if session.scalar(select(Organization).where(Organization.slug == payload.organization_slug)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Organization already exists")
    if session.scalar(select(User).where(User.email == str(payload.owner_email).casefold())):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")
    organization = Organization(name=payload.organization_name.strip(), slug=payload.organization_slug)
    session.add(organization)
    session.flush()
    owner = User(organization_id=organization.id, email=str(payload.owner_email).casefold(), password_hash=password_hash.hash(payload.owner_password), role="owner")
    session.add(owner)
    session.commit()
    return {"organization_id": str(organization.id), "owner_id": str(owner.id)}


@app.post("/api/v1/mobile/auth/login")
def login(payload: LoginRequest, session: Session = Depends(get_session)) -> dict[str, object]:
    user = session.scalar(select(User).where(User.email == str(payload.email).casefold()))
    if user is None or not user.active or not password_hash.verify(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return {"token": token_for(user), "user": {"id": str(user.id), "role": user.role, "organization_id": str(user.organization_id)}}


@app.get("/api/v1/mobile/me")
def me(user: User = Depends(current_user)) -> dict[str, str]:
    return {"id": str(user.id), "email": user.email, "role": user.role, "organization_id": str(user.organization_id)}
