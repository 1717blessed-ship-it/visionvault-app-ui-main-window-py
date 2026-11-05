"""Price list router for managing price lists."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..dependencies import get_db, get_current_organization
from ..models import PriceList, Organization
from ..schemas import (
    PriceListCreate,
    PriceListUpdate,
    PriceListResponse,
    PriceListListResponse,
)

router = APIRouter(prefix="/price-lists", tags=["price-lists"])


@router.post("", response_model=PriceListResponse, status_code=201)
def create_price_list(
    price_list: PriceListCreate,
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
) -> PriceList:
    """Create a new price list."""
    # Check if code already exists in organization
    existing = db.query(PriceList).filter(
        PriceList.organization_id == organization.id,
        PriceList.code == price_list.code
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Price list code already exists")

    db_price_list = PriceList(
        organization_id=organization.id,
        **price_list.model_dump()
    )
    db.add(db_price_list)
    db.commit()
    db.refresh(db_price_list)
    return db_price_list


@router.get("", response_model=PriceListListResponse)
def list_price_lists(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    active_only: bool = Query(True),
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
) -> PriceListListResponse:
    """List price lists with pagination."""
    query = db.query(PriceList).filter(PriceList.organization_id == organization.id)

    if active_only:
        query = query.filter(PriceList.active == True)

    total = query.count()
    price_lists = query.offset((page - 1) * page_size).limit(page_size).all()

    return PriceListListResponse(
        items=price_lists,
        total=total,
        page=page,
        page_size=page_size,
        has_next=page * page_size < total,
        has_previous=page > 1,
    )


@router.get("/{price_list_id}", response_model=PriceListResponse)
def get_price_list(
    price_list_id: UUID,
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
) -> PriceList:
    """Get a specific price list by ID."""
    price_list = db.query(PriceList).filter(
        PriceList.id == price_list_id,
        PriceList.organization_id == organization.id
    ).first()
    if not price_list:
        raise HTTPException(status_code=404, detail="Price list not found")
    return price_list


@router.patch("/{price_list_id}", response_model=PriceListResponse)
def update_price_list(
    price_list_id: UUID,
    price_list_update: PriceListUpdate,
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
) -> PriceList:
    """Update a price list."""
    price_list = db.query(PriceList).filter(
        PriceList.id == price_list_id,
        PriceList.organization_id == organization.id
    ).first()
    if not price_list:
        raise HTTPException(status_code=404, detail="Price list not found")

    # Check if code change conflicts with existing price list
    if price_list_update.code and price_list_update.code != price_list.code:
        existing = db.query(PriceList).filter(
            PriceList.organization_id == organization.id,
            PriceList.code == price_list_update.code
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Price list code already exists")

    for field, value in price_list_update.model_dump(exclude_unset=True).items():
        setattr(price_list, field, value)

    db.commit()
    db.refresh(price_list)
    return price_list


@router.delete("/{price_list_id}", status_code=204, response_model=None)
def delete_price_list(
    price_list_id: UUID,
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
) -> None:
    """Delete a price list (soft delete)."""
    price_list = db.query(PriceList).filter(
        PriceList.id == price_list_id,
        PriceList.organization_id == organization.id
    ).first()
    if not price_list:
        raise HTTPException(status_code=404, detail="Price list not found")

    price_list.deleted_at = datetime.now(timezone.utc)
    db.commit()
