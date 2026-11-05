"""Synchronization API router for mobile offline support.

Provides incremental sync with conflict detection and resolution.
All endpoints are isolated by organization_id through JWT authentication.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import Session

from app.models import Order, Job, ProductionHistory, User
from app.schemas import (
    SyncPullRequest,
    SyncPullResponse,
    SyncPushRequest,
    SyncPushResponse,
    SyncConflict,
    SyncOrder,
    SyncJob,
    SyncProductionHistory,
    SyncPushOrder,
    SyncPushJob,
)
from app.dependencies import get_session, current_user

router = APIRouter(prefix="/api/v1/sync", tags=["sync"])


@router.get("/pull", response_model=SyncPullResponse)
def sync_pull(
    since: datetime = Query(None, description="Only return records updated after this timestamp"),
    table: str = Query(None, description="Filter by table type: orders, jobs, production_history"),
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> SyncPullResponse:
    """Pull changed records from the server for offline synchronization.

    Returns orders, jobs, and production history entries that have been
    created or updated since the given timestamp, filtered by organization.
    """
    org_id = user.organization_id

    # Build base queries with organization isolation
    orders_query = select(Order).where(Order.organization_id == org_id)
    jobs_query = select(Job).where(Job.organization_id == org_id)
    history_query = select(ProductionHistory).where(ProductionHistory.organization_id == org_id)

    # Apply time filter if provided
    if since:
        # Include records updated after 'since' OR soft-deleted after 'since'
        orders_query = orders_query.where(
            or_(
                Order.updated_at >= since,
                and_(Order.deleted_at.isnot(None), Order.deleted_at >= since),
            )
        )
        jobs_query = jobs_query.where(
            or_(
                Job.updated_at >= since,
                and_(Job.deleted_at.isnot(None), Job.deleted_at >= since),
            )
        )
        history_query = history_query.where(ProductionHistory.created_at >= since)

    # Apply table filter if provided
    if table == "orders":
        jobs_query = jobs_query.where(False)  # Empty result
        history_query = history_query.where(False)  # Empty result
    elif table == "jobs":
        orders_query = orders_query.where(False)  # Empty result
        history_query = history_query.where(False)  # Empty result
    elif table == "production_history":
        orders_query = orders_query.where(False)  # Empty result
        jobs_query = jobs_query.where(False)  # Empty result

    # Execute queries
    orders = session.scalars(orders_query.order_by(Order.updated_at.asc())).all()
    jobs = session.scalars(jobs_query.order_by(Job.updated_at.asc())).all()
    history = session.scalars(history_query.order_by(ProductionHistory.created_at.asc())).all()

    # Get current timestamp for next sync
    last_sync = datetime.now(timezone.utc)

    return SyncPullResponse(
        orders=[SyncOrder.model_validate(order) for order in orders],
        jobs=[SyncJob.model_validate(job) for job in jobs],
        production_history=[SyncProductionHistory.model_validate(h) for h in history],
        last_sync=last_sync,
    )


@router.post("/push", response_model=SyncPushResponse)
def sync_push(
    payload: SyncPushRequest,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> SyncPushResponse:
    """Push offline changes to the server with conflict detection.

    Accepts orders and jobs created/modified offline. Validates organization
    ownership, detects version conflicts, and returns conflicts explicitly.
    Uses a transaction to ensure atomicity.
    """
    org_id = user.organization_id
    conflicts: List[SyncConflict] = []
    orders_accepted = 0
    jobs_accepted = 0

    try:
        # Process orders
        for order_data in payload.orders:
            # Check if order exists
            existing_order = session.get(Order, order_data.id)

            if existing_order:
                # Verify organization ownership
                if existing_order.organization_id != org_id:
                    conflicts.append(
                        SyncConflict(
                            type="order",
                            id=order_data.id,
                            server_version=existing_order.version,
                            client_version=order_data.version,
                            message="Order belongs to different organization",
                        )
                    )
                    continue

                # Check for version conflict
                if existing_order.version != order_data.version:
                    conflicts.append(
                        SyncConflict(
                            type="order",
                            id=order_data.id,
                            server_version=existing_order.version,
                            client_version=order_data.version,
                            message="Version conflict: server has newer version",
                        )
                    )
                    continue

                # Update existing order
                existing_order.customer_name = order_data.customer_name
                existing_order.customer_phone = order_data.customer_phone
                existing_order.notes = order_data.notes
                existing_order.urgency = order_data.urgency
                existing_order.delivery_date = order_data.delivery_date
                existing_order.subtotal = float(order_data.subtotal)
                existing_order.total = float(order_data.total)
                existing_order.payment_status = order_data.payment_status
                existing_order.status = order_data.status
                existing_order.deleted_at = order_data.deleted_at
                existing_order.version += 1
                orders_accepted += 1
            else:
                # Create new order
                new_order = Order(
                    id=order_data.id,
                    organization_id=org_id,
                    customer_name=order_data.customer_name,
                    customer_phone=order_data.customer_phone,
                    notes=order_data.notes,
                    urgency=order_data.urgency,
                    delivery_date=order_data.delivery_date,
                    subtotal=float(order_data.subtotal),
                    total=float(order_data.total),
                    payment_status=order_data.payment_status,
                    status=order_data.status,
                    version=order_data.version + 1,
                    deleted_at=order_data.deleted_at,
                )
                session.add(new_order)
                orders_accepted += 1

        # Process jobs
        for job_data in payload.jobs:
            # Check if job exists
            existing_job = session.get(Job, job_data.id)

            if existing_job:
                # Verify organization ownership
                if existing_job.organization_id != org_id:
                    conflicts.append(
                        SyncConflict(
                            type="job",
                            id=job_data.id,
                            server_version=existing_job.version,
                            client_version=job_data.version,
                            message="Job belongs to different organization",
                        )
                    )
                    continue

                # Check for version conflict
                if existing_job.version != job_data.version:
                    conflicts.append(
                        SyncConflict(
                            type="job",
                            id=job_data.id,
                            server_version=existing_job.version,
                            client_version=job_data.version,
                            message="Version conflict: server has newer version",
                        )
                    )
                    continue

                # Update existing job
                existing_job.order_id = job_data.order_id
                existing_job.product_name = job_data.product_name
                existing_job.material = job_data.material
                existing_job.dimensions = job_data.dimensions
                existing_job.job_type = job_data.job_type
                existing_job.quantity = job_data.quantity
                existing_job.unit_price = float(job_data.unit_price)
                existing_job.subtotal = float(job_data.subtotal)
                existing_job.production_status = job_data.production_status
                existing_job.design_status = job_data.design_status
                existing_job.print_count = job_data.print_count
                existing_job.error_count = job_data.error_count
                existing_job.meta_data = job_data.meta_data
                existing_job.deleted_at = job_data.deleted_at
                existing_job.version += 1
                jobs_accepted += 1
            else:
                # Verify order exists and belongs to organization
                order = session.get(Order, job_data.order_id)
                if order is None or order.organization_id != org_id:
                    conflicts.append(
                        SyncConflict(
                            type="job",
                            id=job_data.id,
                            server_version=0,
                            client_version=job_data.version,
                            message="Order not found or belongs to different organization",
                        )
                    )
                    continue

                # Create new job
                new_job = Job(
                    id=job_data.id,
                    organization_id=org_id,
                    order_id=job_data.order_id,
                    product_name=job_data.product_name,
                    material=job_data.material,
                    dimensions=job_data.dimensions,
                    job_type=job_data.job_type,
                    quantity=job_data.quantity,
                    unit_price=float(job_data.unit_price),
                    subtotal=float(job_data.subtotal),
                    production_status=job_data.production_status,
                    design_status=job_data.design_status,
                    print_count=job_data.print_count,
                    error_count=job_data.error_count,
                    meta_data=job_data.meta_data,
                    version=job_data.version + 1,
                    deleted_at=job_data.deleted_at,
                )
                session.add(new_job)
                jobs_accepted += 1

        # Commit transaction
        session.commit()

        return SyncPushResponse(
            success=len(conflicts) == 0,
            conflicts=conflicts,
            orders_accepted=orders_accepted,
            jobs_accepted=jobs_accepted,
            last_sync=datetime.now(timezone.utc),
        )

    except Exception as e:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Sync failed: {str(e)}",
        ) from e
