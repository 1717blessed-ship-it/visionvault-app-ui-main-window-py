"""Price rule router for managing price rules."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..dependencies import get_db, get_current_organization
from ..models import PriceRule, Product, ProductVariant, PriceList, Organization
from ..schemas import (
    PriceRuleCreate,
    PriceRuleUpdate,
    PriceRuleResponse,
    PriceRuleListResponse,
)

router = APIRouter(prefix="/price-rules", tags=["price-rules"])


@router.post("", response_model=PriceRuleResponse, status_code=201)
def create_price_rule(
    rule: PriceRuleCreate,
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
) -> PriceRule:
    """Create a new price rule."""
    # Validate that at least one of product_id or variant_id is provided
    if not rule.product_id and not rule.variant_id:
        raise HTTPException(status_code=400, detail="Either product_id or variant_id must be provided")

    # Verify product/variant exists and belongs to organization
    if rule.product_id:
        product = db.query(Product).filter(
            Product.id == rule.product_id,
            Product.organization_id == organization.id
        ).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

    if rule.variant_id:
        variant = db.query(ProductVariant).filter(
            ProductVariant.id == rule.variant_id,
            ProductVariant.organization_id == organization.id
        ).first()
        if not variant:
            raise HTTPException(status_code=404, detail="Product variant not found")

    if rule.price_list_id:
        price_list = db.query(PriceList).filter(
            PriceList.id == rule.price_list_id,
            PriceList.organization_id == organization.id
        ).first()
        if not price_list:
            raise HTTPException(status_code=404, detail="Price list not found")

    db_rule = PriceRule(
        organization_id=organization.id,
        **rule.model_dump()
    )
    db.add(db_rule)
    db.commit()
    db.refresh(db_rule)
    return db_rule


@router.get("", response_model=PriceRuleListResponse)
def list_price_rules(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    active_only: bool = Query(True),
    product_id: Optional[UUID] = None,
    variant_id: Optional[UUID] = None,
    price_list_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
) -> PriceRuleListResponse:
    """List price rules with pagination."""
    query = db.query(PriceRule).filter(PriceRule.organization_id == organization.id)

    if active_only:
        query = query.filter(PriceRule.active == True)

    if product_id:
        query = query.filter(PriceRule.product_id == product_id)

    if variant_id:
        query = query.filter(PriceRule.variant_id == variant_id)

    if price_list_id:
        query = query.filter(PriceRule.price_list_id == price_list_id)

    total = query.count()
    rules = query.offset((page - 1) * page_size).limit(page_size).all()

    return PriceRuleListResponse(
        items=rules,
        total=total,
        page=page,
        page_size=page_size,
        has_next=page * page_size < total,
        has_previous=page > 1,
    )


@router.get("/{rule_id}", response_model=PriceRuleResponse)
def get_price_rule(
    rule_id: UUID,
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
) -> PriceRule:
    """Get a specific price rule by ID."""
    rule = db.query(PriceRule).filter(
        PriceRule.id == rule_id,
        PriceRule.organization_id == organization.id
    ).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Price rule not found")
    return rule


@router.patch("/{rule_id}", response_model=PriceRuleResponse)
def update_price_rule(
    rule_id: UUID,
    rule_update: PriceRuleUpdate,
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
) -> PriceRule:
    """Update a price rule."""
    rule = db.query(PriceRule).filter(
        PriceRule.id == rule_id,
        PriceRule.organization_id == organization.id
    ).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Price rule not found")

    # Validate product/variant/price_list if provided
    if rule_update.product_id is not None:
        product = db.query(Product).filter(
            Product.id == rule_update.product_id,
            Product.organization_id == organization.id
        ).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

    if rule_update.variant_id is not None:
        variant = db.query(ProductVariant).filter(
            ProductVariant.id == rule_update.variant_id,
            ProductVariant.organization_id == organization.id
        ).first()
        if not variant:
            raise HTTPException(status_code=404, detail="Product variant not found")

    if rule_update.price_list_id is not None:
        price_list = db.query(PriceList).filter(
            PriceList.id == rule_update.price_list_id,
            PriceList.organization_id == organization.id
        ).first()
        if not price_list:
            raise HTTPException(status_code=404, detail="Price list not found")

    for field, value in rule_update.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)

    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/{rule_id}", status_code=204, response_model=None)
def delete_price_rule(
    rule_id: UUID,
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
) -> None:
    """Delete a price rule (soft delete)."""
    rule = db.query(PriceRule).filter(
        PriceRule.id == rule_id,
        PriceRule.organization_id == organization.id
    ).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Price rule not found")

    rule.deleted_at = datetime.now(timezone.utc)
    db.commit()
