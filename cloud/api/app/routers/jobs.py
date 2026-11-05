"""Jobs API router with CRUD endpoints.

All endpoints are isolated by organization_id through JWT authentication.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session

from app.models import Job, Order, User
from app.schemas import (
    JobCreate,
    JobUpdate,
    JobResponse,
    JobListResponse,
    PaginationParams,
    JobFilterParams,
)
from app.dependencies import get_session, current_user

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


def get_pagination_params(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PaginationParams:
    """Extract pagination parameters from query string."""
    return PaginationParams(page=page, page_size=page_size)


def get_job_filter_params(
    order_id: Optional[UUID] = Query(None),
    production_status: Optional[str] = Query(None),
    design_status: Optional[str] = Query(None),
    job_type: Optional[str] = Query(None),
    since: Optional[datetime] = Query(None),
) -> JobFilterParams:
    """Extract job filter parameters from query string."""
    return JobFilterParams(
        order_id=order_id,
        production_status=production_status,
        design_status=design_status,
        job_type=job_type,
        since=since,
    )


@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
def create_job(
    payload: JobCreate,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> Job:
    """Create a new job for the authenticated user's organization."""
    # Verify order exists and belongs to the same organization
    order = session.scalar(
        select(Order).where(
            and_(
                Order.id == payload.order_id,
                Order.organization_id == user.organization_id,
                Order.deleted_at.is_(None),
            )
        )
    )
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    job = Job(
        organization_id=user.organization_id,
        order_id=payload.order_id,
        product_name=payload.product_name,
        material=payload.material,
        dimensions=payload.dimensions,
        job_type=payload.job_type,
        quantity=payload.quantity,
        unit_price=float(payload.unit_price),
        subtotal=float(payload.subtotal),
        production_status=payload.production_status,
        design_status=payload.design_status,
        print_count=payload.print_count,
        error_count=payload.error_count,
        meta_data=payload.meta_data,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


@router.get("", response_model=JobListResponse)
def list_jobs(
    pagination: PaginationParams = Depends(get_pagination_params),
    filters: JobFilterParams = Depends(get_job_filter_params),
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> JobListResponse:
    """List jobs for the authenticated user's organization with pagination and filtering."""
    # Build base query with organization isolation
    query = select(Job).where(Job.organization_id == user.organization_id)

    # Apply filters
    if filters.order_id:
        query = query.where(Job.order_id == filters.order_id)
    if filters.production_status:
        query = query.where(Job.production_status == filters.production_status)
    if filters.design_status:
        query = query.where(Job.design_status == filters.design_status)
    if filters.job_type:
        query = query.where(Job.job_type == filters.job_type)
    if filters.since:
        query = query.where(Job.updated_at >= filters.since)

    # Exclude soft-deleted records
    query = query.where(Job.deleted_at.is_(None))

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = session.scalar(count_query) or 0

    # Apply pagination
    offset = (pagination.page - 1) * pagination.page_size
    query = query.order_by(Job.created_at.desc()).offset(offset).limit(pagination.page_size)

    # Execute query
    jobs = session.scalars(query).all()

    return JobListResponse(
        items=jobs,
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        has_next=offset + pagination.page_size < total,
        has_previous=pagination.page > 1,
    )


@router.get("/{job_id}", response_model=JobResponse)
def get_job(
    job_id: UUID,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> Job:
    """Retrieve a specific job by ID."""
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
    return job


@router.put("/{job_id}", response_model=JobResponse)
def update_job(
    job_id: UUID,
    payload: JobUpdate,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> Job:
    """Update an existing job."""
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

    # Update fields if provided
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field in ["unit_price", "subtotal"]:
            setattr(job, field, float(value))
        else:
            setattr(job, field, value)

    # Increment version for sync
    job.version += 1

    session.commit()
    session.refresh(job)
    return job


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def archive_job(
    job_id: UUID,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> None:
    """Soft-delete (archive) a job."""
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

    job.deleted_at = datetime.now(timezone.utc)
    job.version += 1
    session.commit()
