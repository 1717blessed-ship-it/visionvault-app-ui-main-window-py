"""Configuration settings for the API.

Separated to avoid circular imports.
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "")
JWT_SECRET = os.environ.get("JWT_SECRET", "")
BOOTSTRAP_TOKEN = os.environ.get("BOOTSTRAP_TOKEN", "")

if not DATABASE_URL or not JWT_SECRET or not BOOTSTRAP_TOKEN:
    raise RuntimeError("DATABASE_URL, JWT_SECRET y BOOTSTRAP_TOKEN son obligatorios")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
