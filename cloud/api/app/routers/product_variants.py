"""Product variant router for managing product variants."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..dependencies import get_db, get_current_organization
from ..models import ProductVariant, Product, Organization
from ..schemas import (
    ProductVariantCreate,
    ProductVariantUpdate,
    ProductVariantResponse,
    ProductVariantListResponse,
)

router = APIRouter(prefix="/product-variants", tags=["product-variants"])


@router.post("", response_model=ProductVariantResponse, status_code=201)
def create_product_variant(
    variant: ProductVariantCreate,
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
) -> ProductVariant:
    """Create a new product variant."""
    # Verify product exists and belongs to organization
    product = db.query(Product).filter(
        Product.id == variant.product_id,
        Product.organization_id == organization.id
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Check if code already exists in organization
    existing = db.query(ProductVariant).filter(
        ProductVariant.organization_id == organization.id,
        ProductVariant.code == variant.code
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Variant code already exists")

    db_variant = ProductVariant(
        organization_id=organization.id,
        **variant.model_dump()
    )
    db.add(db_variant)
    db.commit()
    db.refresh(db_variant)
    return db_variant


@router.get("", response_model=ProductVariantListResponse)
def list_product_variants(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    active_only: bool = Query(True),
    product_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
) -> ProductVariantListResponse:
    """List product variants with pagination."""
    query = db.query(ProductVariant).filter(ProductVariant.organization_id == organization.id)

    if active_only:
        query = query.filter(ProductVariant.active == True)

    if product_id:
        query = query.filter(ProductVariant.product_id == product_id)

    total = query.count()
    variants = query.offset((page - 1) * page_size).limit(page_size).all()

    return ProductVariantListResponse(
        items=variants,
        total=total,
        page=page,
        page_size=page_size,
        has_next=page * page_size < total,
        has_previous=page > 1,
    )


@router.get("/{variant_id}", response_model=ProductVariantResponse)
def get_product_variant(
    variant_id: UUID,
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
) -> ProductVariant:
    """Get a specific product variant by ID."""
    variant = db.query(ProductVariant).filter(
        ProductVariant.id == variant_id,
        ProductVariant.organization_id == organization.id
    ).first()
    if not variant:
        raise HTTPException(status_code=404, detail="Product variant not found")
    return variant


@router.patch("/{variant_id}", response_model=ProductVariantResponse)
def update_product_variant(
    variant_id: UUID,
    variant_update: ProductVariantUpdate,
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
) -> ProductVariant:
    """Update a product variant."""
    variant = db.query(ProductVariant).filter(
        ProductVariant.id == variant_id,
        ProductVariant.organization_id == organization.id
    ).first()
    if not variant:
        raise HTTPException(status_code=404, detail="Product variant not found")

    # Check if code change conflicts with existing variant
    if variant_update.code and variant_update.code != variant.code:
        existing = db.query(ProductVariant).filter(
            ProductVariant.organization_id == organization.id,
            ProductVariant.code == variant_update.code
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Variant code already exists")

    for field, value in variant_update.model_dump(exclude_unset=True).items():
        setattr(variant, field, value)

    db.commit()
    db.refresh(variant)
    return variant


@router.delete("/{variant_id}", status_code=204, response_model=None)
def delete_product_variant(
    variant_id: UUID,
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
) -> None:
    """Delete a product variant (soft delete)."""
    variant = db.query(ProductVariant).filter(
        ProductVariant.id == variant_id,
        ProductVariant.organization_id == organization.id
    ).first()
    if not variant:
        raise HTTPException(status_code=404, detail="Product variant not found")

    variant.deleted_at = datetime.now(timezone.utc)
    db.commit()
