"""Production History API router.

Tracks job status changes for audit trail and synchronization.
All endpoints are isolated by organization_id through JWT authentication.
"""
from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from app.models import ProductionHistory, Job, User
from app.schemas import (
    ProductionHistoryCreate,
    ProductionHistoryResponse,
)
from app.dependencies import get_session, current_user

router = APIRouter(prefix="/api/v1/production-history", tags=["production-history"])


@router.post("", response_model=ProductionHistoryResponse, status_code=status.HTTP_201_CREATED)
def create_production_history(
    payload: ProductionHistoryCreate,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> ProductionHistory:
    """Create a new production history entry for a job status change."""
    # Verify job exists and belongs to the same organization
    job = session.scalar(
        select(Job).where(
            and_(
                Job.id == payload.job_id,
                Job.organization_id == user.organization_id,
                Job.deleted_at.is_(None),
            )
        )
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    history = ProductionHistory(
        organization_id=user.organization_id,
        job_id=payload.job_id,
        user_id=user.id,
        previous_status=payload.previous_status,
        new_status=payload.new_status,
        note=payload.note,
    )
    session.add(history)
    session.commit()
    session.refresh(history)
    return history


@router.get("/job/{job_id}", response_model=List[ProductionHistoryResponse])
def get_job_production_history(
    job_id: UUID,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> List[ProductionHistory]:
    """Retrieve all production history entries for a specific job."""
    # Verify job exists and belongs to the same organization
    job = session.scalar(
        select(Job).where(
            and_(
                Job.id == job_id,
                Job.organization_id == user.organization_id,
                Job.deleted_at.is_(None),
            )
        )
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    history_entries = session.scalars(
        select(ProductionHistory)
        .where(
            and_(
                ProductionHistory.job_id == job_id,
                ProductionHistory.organization_id == user.organization_id,
            )
        )
        .order_by(ProductionHistory.created_at.desc())
    ).all()

    return history_entries
