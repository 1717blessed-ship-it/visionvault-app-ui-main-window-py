"""Pydantic schemas for API requests and responses.

Provides validation and serialization for all API endpoints.
Does not expose SQLAlchemy models directly.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, ConfigDict
from decimal import Decimal


# ============================================================================
# Organization and User Schemas
# ============================================================================

class OrganizationResponse(BaseModel):
    """Organization response schema."""
    id: UUID
    name: str
    slug: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserResponse(BaseModel):
    """User response schema."""
    id: UUID
    email: str
    role: str
    organization_id: UUID
    active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# Order Schemas
# ============================================================================

class OrderCreate(BaseModel):
    """Schema for creating a new order."""
    customer_name: str = Field(min_length=1, max_length=200)
    customer_phone: Optional[str] = Field(None, max_length=50)
    notes: Optional[str] = None
    urgency: str = Field(default="normal", pattern=r"^(normal|high|urgent)$")
    delivery_date: Optional[datetime] = None
    subtotal: Decimal = Field(default=0, ge=0)
    total: Decimal = Field(default=0, ge=0)
    payment_status: str = Field(default="pending", pattern=r"^(pending|partial|paid|cancelled)$")
    status: str = Field(default="pending", pattern=r"^(pending|accepted|in_design|in_production|ready|delivered|cancelled)$")


class OrderUpdate(BaseModel):
    """Schema for updating an order."""
    customer_name: Optional[str] = Field(None, min_length=1, max_length=200)
    customer_phone: Optional[str] = Field(None, max_length=50)
    notes: Optional[str] = None
    urgency: Optional[str] = Field(None, pattern=r"^(normal|high|urgent)$")
    delivery_date: Optional[datetime] = None
    subtotal: Optional[Decimal] = Field(None, ge=0)
    total: Optional[Decimal] = Field(None, ge=0)
    payment_status: Optional[str] = Field(None, pattern=r"^(pending|partial|paid|cancelled)$")
    status: Optional[str] = Field(None, pattern=r"^(pending|accepted|in_design|in_production|ready|delivered|cancelled)$")


class OrderResponse(BaseModel):
    """Schema for order response."""
    id: UUID
    organization_id: UUID
    customer_name: str
    customer_phone: Optional[str]
    notes: Optional[str]
    urgency: str
    delivery_date: Optional[datetime]
    subtotal: Decimal
    total: Decimal
    payment_status: str
    status: str
    version: int
    deleted_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OrderListResponse(BaseModel):
    """Schema for paginated order list response."""
    items: List[OrderResponse]
    total: int
    page: int
    page_size: int
    has_next: bool
    has_previous: bool


# ============================================================================
# Job Schemas
# ============================================================================

class JobCreate(BaseModel):
    """Schema for creating a new job."""
    order_id: UUID
    product_name: str = Field(min_length=1, max_length=200)
    material: Optional[str] = Field(None, max_length=100)
    dimensions: Optional[str] = Field(None, max_length=100)
    job_type: str = Field(default="sticker_sheet", pattern=r"^(sticker_sheet|individual_sticker|print|sublimation|custom_product)$")
    quantity: int = Field(default=1, gt=0)
    unit_price: Decimal = Field(default=0, ge=0)
    subtotal: Decimal = Field(default=0, ge=0)
    production_status: str = Field(default="pending", pattern=r"^(pending|in_progress|completed|cancelled)$")
    design_status: str = Field(default="pending", pattern=r"^(pending|in_progress|approved|cancelled)$")
    print_count: int = Field(default=0, ge=0)
    error_count: int = Field(default=0, ge=0)
    meta_data: Optional[dict] = None
    product_id: Optional[UUID] = None
    variant_id: Optional[UUID] = None
    price_list_id: Optional[UUID] = None
    price_rule_id: Optional[UUID] = None


class JobUpdate(BaseModel):
    """Schema for updating a job."""
    product_name: Optional[str] = Field(None, min_length=1, max_length=200)
    material: Optional[str] = Field(None, max_length=100)
    dimensions: Optional[str] = Field(None, max_length=100)
    job_type: Optional[str] = Field(None, pattern=r"^(sticker_sheet|individual_sticker|print|sublimation|custom_product)$")
    quantity: Optional[int] = Field(None, gt=0)
    unit_price: Optional[Decimal] = Field(None, ge=0)
    subtotal: Optional[Decimal] = Field(None, ge=0)
    production_status: Optional[str] = Field(None, pattern=r"^(pending|in_progress|completed|cancelled)$")
    design_status: Optional[str] = Field(None, pattern=r"^(pending|in_progress|approved|cancelled)$")
    print_count: Optional[int] = Field(None, ge=0)
    error_count: Optional[int] = Field(None, ge=0)
    meta_data: Optional[dict] = None
    product_id: Optional[UUID] = None
    variant_id: Optional[UUID] = None
    price_list_id: Optional[UUID] = None
    price_rule_id: Optional[UUID] = None


class JobResponse(BaseModel):
    """Schema for job response."""
    id: UUID
    organization_id: UUID
    order_id: UUID
    product_name: str
    material: Optional[str]
    dimensions: Optional[str]
    job_type: str
    quantity: int
    unit_price: Decimal
    subtotal: Decimal
    production_status: str
    design_status: str
    print_count: int
    error_count: int
    meta_data: Optional[dict]
    product_id: Optional[UUID]
    variant_id: Optional[UUID]
    price_list_id: Optional[UUID]
    price_rule_id: Optional[UUID]
    version: int
    deleted_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class JobListResponse(BaseModel):
    """Schema for paginated job list response."""
    items: List[JobResponse]
    total: int
    page: int
    page_size: int
    has_next: bool
    has_previous: bool


# ============================================================================
# Production History Schemas
# ============================================================================

class ProductionHistoryCreate(BaseModel):
    """Schema for creating a production history entry."""
    job_id: UUID
    previous_status: Optional[str] = None
    new_status: str = Field(min_length=1, max_length=20)
    note: Optional[str] = None


class ProductionHistoryResponse(BaseModel):
    """Schema for production history response."""
    id: UUID
    organization_id: UUID
    job_id: UUID
    user_id: Optional[UUID]
    previous_status: Optional[str]
    new_status: str
    note: Optional[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# Sync Schemas
# ============================================================================

class SyncPullRequest(BaseModel):
    """Schema for sync pull request."""
    since: Optional[datetime] = None
    table: Optional[str] = Field(None, pattern=r"^(orders|jobs|production_history)$")


class SyncOrder(BaseModel):
    """Schema for synced order."""
    id: UUID
    organization_id: UUID
    customer_name: str
    customer_phone: Optional[str]
    notes: Optional[str]
    urgency: str
    delivery_date: Optional[datetime]
    subtotal: Decimal
    total: Decimal
    payment_status: str
    status: str
    version: int
    deleted_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SyncJob(BaseModel):
    """Schema for synced job."""
    id: UUID
    organization_id: UUID
    order_id: UUID
    product_name: str
    material: Optional[str]
    dimensions: Optional[str]
    job_type: str
    quantity: int
    unit_price: Decimal
    subtotal: Decimal
    production_status: str
    design_status: str
    print_count: int
    error_count: int
    meta_data: Optional[dict]
    version: int
    deleted_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SyncProductionHistory(BaseModel):
    """Schema for synced production history."""
    id: UUID
    organization_id: UUID
    job_id: UUID
    user_id: Optional[UUID]
    previous_status: Optional[str]
    new_status: str
    note: Optional[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SyncPullResponse(BaseModel):
    """Schema for sync pull response."""
    orders: List[SyncOrder]
    jobs: List[SyncJob]
    production_history: List[SyncProductionHistory]
    last_sync: datetime


class SyncPushOrder(BaseModel):
    """Schema for pushing an order."""
    id: UUID
    organization_id: UUID
    customer_name: str
    customer_phone: Optional[str]
    notes: Optional[str]
    urgency: str
    delivery_date: Optional[datetime]
    subtotal: Decimal
    total: Decimal
    payment_status: str
    status: str
    version: int
    deleted_at: Optional[datetime]


class SyncPushJob(BaseModel):
    """Schema for pushing a job."""
    id: UUID
    organization_id: UUID
    order_id: UUID
    product_name: str
    material: Optional[str]
    dimensions: Optional[str]
    job_type: str
    quantity: int
    unit_price: Decimal
    subtotal: Decimal
    production_status: str
    design_status: str
    print_count: int
    error_count: int
    meta_data: Optional[dict]
    version: int
    deleted_at: Optional[datetime]


class SyncPushRequest(BaseModel):
    """Schema for sync push request."""
    orders: List[SyncPushOrder] = []
    jobs: List[SyncPushJob] = []


class SyncConflict(BaseModel):
    """Schema for sync conflict."""
    type: str  # "order" or "job"
    id: UUID
    server_version: int
    client_version: int
    message: str


class SyncPushResponse(BaseModel):
    """Schema for sync push response."""
    success: bool
    conflicts: List[SyncConflict]
    orders_accepted: int
    jobs_accepted: int
    last_sync: datetime


# ============================================================================
# Pagination and Filtering
# ============================================================================

class PaginationParams(BaseModel):
    """Schema for pagination parameters."""
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class OrderFilterParams(BaseModel):
    """Schema for order filtering parameters."""
    status: Optional[str] = Field(None, pattern=r"^(pending|accepted|in_design|in_production|ready|delivered|cancelled)$")
    payment_status: Optional[str] = Field(None, pattern=r"^(pending|partial|paid|cancelled)$")
    urgency: Optional[str] = Field(None, pattern=r"^(normal|high|urgent)$")
    customer_name: Optional[str] = None
    since: Optional[datetime] = None


class JobFilterParams(BaseModel):
    """Schema for job filtering parameters."""
    order_id: Optional[UUID] = None
    production_status: Optional[str] = Field(None, pattern=r"^(pending|in_progress|completed|cancelled)$")
    design_status: Optional[str] = Field(None, pattern=r"^(pending|in_progress|approved|cancelled)$")
    job_type: Optional[str] = Field(None, pattern=r"^(sticker_sheet|individual_sticker|print|sublimation|custom_product)$")
    since: Optional[datetime] = None


# ============================================================================
# Product Schemas
# ============================================================================

class ProductCreate(BaseModel):
    """Schema for creating a new product."""
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=100)
    image_path: Optional[str] = Field(None, max_length=500)
    base_price: Optional[Decimal] = Field(None, ge=0)
    active: bool = Field(default=True)


class ProductUpdate(BaseModel):
    """Schema for updating a product."""
    code: Optional[str] = Field(None, min_length=1, max_length=50)
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=100)
    image_path: Optional[str] = Field(None, max_length=500)
    base_price: Optional[Decimal] = Field(None, ge=0)
    active: Optional[bool] = None


class ProductResponse(BaseModel):
    """Schema for product response."""
    id: UUID
    organization_id: UUID
    code: str
    name: str
    description: Optional[str]
    category: Optional[str]
    image_path: Optional[str]
    base_price: Optional[Decimal]
    active: bool
    version: int
    deleted_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProductListResponse(BaseModel):
    """Schema for paginated product list response."""
    items: List[ProductResponse]
    total: int
    page: int
    page_size: int
    has_next: bool
    has_previous: bool


# ============================================================================
# Product Variant Schemas
# ============================================================================

class ProductVariantCreate(BaseModel):
    """Schema for creating a new product variant."""
    product_id: UUID
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    line: Optional[str] = Field(None, max_length=100)
    material: Optional[str] = Field(None, max_length=100)
    size: Optional[str] = Field(None, max_length=100)
    modality: Optional[str] = Field(None, max_length=100)
    active: bool = Field(default=True)


class ProductVariantUpdate(BaseModel):
    """Schema for updating a product variant."""
    code: Optional[str] = Field(None, min_length=1, max_length=50)
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    line: Optional[str] = Field(None, max_length=100)
    material: Optional[str] = Field(None, max_length=100)
    size: Optional[str] = Field(None, max_length=100)
    modality: Optional[str] = Field(None, max_length=100)
    active: Optional[bool] = None


class ProductVariantResponse(BaseModel):
    """Schema for product variant response."""
    id: UUID
    organization_id: UUID
    product_id: UUID
    code: str
    name: str
    line: Optional[str]
    material: Optional[str]
    size: Optional[str]
    modality: Optional[str]
    active: bool
    version: int
    deleted_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProductVariantListResponse(BaseModel):
    """Schema for paginated product variant list response."""
    items: List[ProductVariantResponse]
    total: int
    page: int
    page_size: int
    has_next: bool
    has_previous: bool


# ============================================================================
# Price List Schemas
# ============================================================================

class PriceListCreate(BaseModel):
    """Schema for creating a new price list."""
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    active: bool = Field(default=True)


class PriceListUpdate(BaseModel):
    """Schema for updating a price list."""
    code: Optional[str] = Field(None, min_length=1, max_length=50)
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    active: Optional[bool] = None


class PriceListResponse(BaseModel):
    """Schema for price list response."""
    id: UUID
    organization_id: UUID
    code: str
    name: str
    active: bool
    version: int
    deleted_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PriceListListResponse(BaseModel):
    """Schema for paginated price list list response."""
    items: List[PriceListResponse]
    total: int
    page: int
    page_size: int
    has_next: bool
    has_previous: bool


# ============================================================================
# Price Rule Schemas
# ============================================================================

class PriceRuleCreate(BaseModel):
    """Schema for creating a new price rule."""
    rule_name: str = Field(min_length=1, max_length=200)
    product_id: Optional[UUID] = None
    variant_id: Optional[UUID] = None
    price_list_id: Optional[UUID] = None
    max_quantity: Optional[int] = Field(None, ge=0)
    priority: int = Field(default=0, ge=0)
    preparation_limit: Optional[int] = Field(None, ge=0)

    # Cost calculation modes
    cost_mp_mode: str = Field(default="percent", pattern=r"^(percent|fixed|unit)$")
    cost_mp_percent: Decimal = Field(default=0, ge=0)
    cost_mp_fixed: Decimal = Field(default=0, ge=0)
    cost_mp_unit: Decimal = Field(default=0, ge=0)

    cost_mo_mode: str = Field(default="percent", pattern=r"^(percent|fixed|unit)$")
    cost_mo_percent: Decimal = Field(default=0, ge=0)
    cost_mo_fixed: Decimal = Field(default=0, ge=0)
    cost_mo_unit: Decimal = Field(default=0, ge=0)

    cost_cf_mode: str = Field(default="percent", pattern=r"^(percent|fixed|unit)$")
    cost_cf_percent: Decimal = Field(default=0, ge=0)
    cost_cf_fixed: Decimal = Field(default=0, ge=0)
    cost_cf_unit: Decimal = Field(default=0, ge=0)

    components_json: Optional[str] = None
    active: bool = Field(default=True)


class PriceRuleUpdate(BaseModel):
    """Schema for updating a price rule."""
    rule_name: Optional[str] = Field(None, min_length=1, max_length=200)
    product_id: Optional[UUID] = None
    variant_id: Optional[UUID] = None
    price_list_id: Optional[UUID] = None
    max_quantity: Optional[int] = Field(None, ge=0)
    priority: Optional[int] = Field(None, ge=0)
    preparation_limit: Optional[int] = Field(None, ge=0)

    cost_mp_mode: Optional[str] = Field(None, pattern=r"^(percent|fixed|unit)$")
    cost_mp_percent: Optional[Decimal] = Field(None, ge=0)
    cost_mp_fixed: Optional[Decimal] = Field(None, ge=0)
    cost_mp_unit: Optional[Decimal] = Field(None, ge=0)

    cost_mo_mode: Optional[str] = Field(None, pattern=r"^(percent|fixed|unit)$")
    cost_mo_percent: Optional[Decimal] = Field(None, ge=0)
    cost_mo_fixed: Optional[Decimal] = Field(None, ge=0)
    cost_mo_unit: Optional[Decimal] = Field(None, ge=0)

    cost_cf_mode: Optional[str] = Field(None, pattern=r"^(percent|fixed|unit)$")
    cost_cf_percent: Optional[Decimal] = Field(None, ge=0)
    cost_cf_fixed: Optional[Decimal] = Field(None, ge=0)
    cost_cf_unit: Optional[Decimal] = Field(None, ge=0)

    components_json: Optional[str] = None
    active: Optional[bool] = None


class PriceRuleResponse(BaseModel):
    """Schema for price rule response."""
    id: UUID
    organization_id: UUID
    rule_name: str
    product_id: Optional[UUID]
    variant_id: Optional[UUID]
    price_list_id: Optional[UUID]
    max_quantity: Optional[int]
    priority: int
    preparation_limit: Optional[int]

    cost_mp_mode: str
    cost_mp_percent: Decimal
    cost_mp_fixed: Decimal
    cost_mp_unit: Decimal

    cost_mo_mode: str
    cost_mo_percent: Decimal
    cost_mo_fixed: Decimal
    cost_mo_unit: Decimal

    cost_cf_mode: str
    cost_cf_percent: Decimal
    cost_cf_fixed: Decimal
    cost_cf_unit: Decimal

    components_json: Optional[str]
    active: bool
    version: int
    deleted_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PriceRuleListResponse(BaseModel):
    """Schema for paginated price rule list response."""
    items: List[PriceRuleResponse]
    total: int
    page: int
    page_size: int
    has_next: bool
    has_previous: bool
