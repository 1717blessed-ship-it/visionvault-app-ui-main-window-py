"""Product router for managing product catalog."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..dependencies import get_db, get_current_organization
from ..models import Product, Organization
from ..schemas import (
    ProductCreate,
    ProductUpdate,
    ProductResponse,
    ProductListResponse,
    PaginationParams,
)

router = APIRouter(prefix="/products", tags=["products"])


@router.post("", response_model=ProductResponse, status_code=201)
def create_product(
    product: ProductCreate,
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
) -> Product:
    """Create a new product."""
    # Check if code already exists in organization
    existing = db.query(Product).filter(
        Product.organization_id == organization.id,
        Product.code == product.code
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Product code already exists")

    db_product = Product(
        organization_id=organization.id,
        **product.model_dump()
    )
    db.add(db_product)
    db.commit()
    db.refresh(db_product)
    return db_product


@router.get("", response_model=ProductListResponse)
def list_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    active_only: bool = Query(True),
    category: Optional[str] = None,
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
) -> ProductListResponse:
    """List products with pagination."""
    query = db.query(Product).filter(Product.organization_id == organization.id)

    if active_only:
        query = query.filter(Product.active == True)

    if category:
        query = query.filter(Product.category == category)

    total = query.count()
    products = query.offset((page - 1) * page_size).limit(page_size).all()

    return ProductListResponse(
        items=products,
        total=total,
        page=page,
        page_size=page_size,
        has_next=page * page_size < total,
        has_previous=page > 1,
    )


@router.get("/{product_id}", response_model=ProductResponse)
def get_product(
    product_id: UUID,
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
) -> Product:
    """Get a specific product by ID."""
    product = db.query(Product).filter(
        Product.id == product_id,
        Product.organization_id == organization.id
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.patch("/{product_id}", response_model=ProductResponse)
def update_product(
    product_id: UUID,
    product_update: ProductUpdate,
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
) -> Product:
    """Update a product."""
    product = db.query(Product).filter(
        Product.id == product_id,
        Product.organization_id == organization.id
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Check if code change conflicts with existing product
    if product_update.code and product_update.code != product.code:
        existing = db.query(Product).filter(
            Product.organization_id == organization.id,
            Product.code == product_update.code
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Product code already exists")

    for field, value in product_update.model_dump(exclude_unset=True).items():
        setattr(product, field, value)

    db.commit()
    db.refresh(product)
    return product


@router.delete("/{product_id}", status_code=204, response_model=None)
def delete_product(
    product_id: UUID,
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
) -> None:
    """Delete a product (soft delete)."""
    product = db.query(Product).filter(
        Product.id == product_id,
        Product.organization_id == organization.id
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    product.deleted_at = datetime.now(timezone.utc)
    db.commit()
