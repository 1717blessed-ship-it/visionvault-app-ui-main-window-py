"""Orders API router with CRUD endpoints.

All endpoints are isolated by organization_id through JWT authentication.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import Session

from app.models import Order, User
from app.schemas import (
    OrderCreate,
    OrderUpdate,
    OrderResponse,
    OrderListResponse,
    PaginationParams,
    OrderFilterParams,
)
from app.dependencies import get_session, current_user

router = APIRouter(prefix="/api/v1/orders", tags=["orders"])


def get_pagination_params(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PaginationParams:
    """Extract pagination parameters from query string."""
    return PaginationParams(page=page, page_size=page_size)


def get_order_filter_params(
    status: Optional[str] = Query(None),
    payment_status: Optional[str] = Query(None),
    urgency: Optional[str] = Query(None),
    customer_name: Optional[str] = Query(None),
    since: Optional[datetime] = Query(None),
) -> OrderFilterParams:
    """Extract order filter parameters from query string."""
    return OrderFilterParams(
        status=status,
        payment_status=payment_status,
        urgency=urgency,
        customer_name=customer_name,
        since=since,
    )


@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
def create_order(
    payload: OrderCreate,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> Order:
    """Create a new order for the authenticated user's organization."""
    order = Order(
        organization_id=user.organization_id,
        customer_name=payload.customer_name,
        customer_phone=payload.customer_phone,
        notes=payload.notes,
        urgency=payload.urgency,
        delivery_date=payload.delivery_date,
        subtotal=float(payload.subtotal),
        total=float(payload.total),
        payment_status=payload.payment_status,
        status=payload.status,
    )
    session.add(order)
    session.commit()
    session.refresh(order)
    return order


@router.get("", response_model=OrderListResponse)
def list_orders(
    pagination: PaginationParams = Depends(get_pagination_params),
    filters: OrderFilterParams = Depends(get_order_filter_params),
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> OrderListResponse:
    """List orders for the authenticated user's organization with pagination and filtering."""
    # Build base query with organization isolation
    query = select(Order).where(Order.organization_id == user.organization_id)

    # Apply filters
    if filters.status:
        query = query.where(Order.status == filters.status)
    if filters.payment_status:
        query = query.where(Order.payment_status == filters.payment_status)
    if filters.urgency:
        query = query.where(Order.urgency == filters.urgency)
    if filters.customer_name:
        query = query.where(Order.customer_name.ilike(f"%{filters.customer_name}%"))
    if filters.since:
        query = query.where(Order.updated_at >= filters.since)

    # Exclude soft-deleted records
    query = query.where(Order.deleted_at.is_(None))

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = session.scalar(count_query) or 0

    # Apply pagination
    offset = (pagination.page - 1) * pagination.page_size
    query = query.order_by(Order.created_at.desc()).offset(offset).limit(pagination.page_size)

    # Execute query
    orders = session.scalars(query).all()

    return OrderListResponse(
        items=orders,
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        has_next=offset + pagination.page_size < total,
        has_previous=pagination.page > 1,
    )


@router.get("/{order_id}", response_model=OrderResponse)
def get_order(
    order_id: UUID,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> Order:
    """Retrieve a specific order by ID."""
    order = session.scalar(
        select(Order).where(
            and_(
                Order.id == order_id,
                Order.organization_id == user.organization_id,
                Order.deleted_at.is_(None),
            )
        )
    )
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return order


@router.put("/{order_id}", response_model=OrderResponse)
def update_order(
    order_id: UUID,
    payload: OrderUpdate,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> Order:
    """Update an existing order."""
    order = session.scalar(
        select(Order).where(
            and_(
                Order.id == order_id,
                Order.organization_id == user.organization_id,
                Order.deleted_at.is_(None),
            )
        )
    )
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    # Update fields if provided
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field in ["subtotal", "total"]:
            setattr(order, field, float(value))
        else:
            setattr(order, field, value)

    # Increment version for sync
    order.version += 1

    session.commit()
    session.refresh(order)
    return order


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def archive_order(
    order_id: UUID,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> None:
    """Soft-delete (archive) an order."""
    order = session.scalar(
        select(Order).where(
            and_(
                Order.id == order_id,
                Order.organization_id == user.organization_id,
                Order.deleted_at.is_(None),
            )
        )
    )
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    order.deleted_at = datetime.now(timezone.utc)
    order.version += 1
    session.commit()
