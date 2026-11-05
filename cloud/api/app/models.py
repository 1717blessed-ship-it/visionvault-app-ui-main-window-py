"""Database models for Doccione Cloud API.

Includes models for organizations, users, orders, jobs, and production history.
All models include organization isolation and sync fields for mobile synchronization.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, Index, JSON, Integer, Numeric, Boolean, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


class TimestampMixin:
    """Mixin for created_at and updated_at timestamps."""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )


class SyncMixin:
    """Mixin for synchronization fields."""
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True
    )


class Organization(Base, TimestampMixin):
    """Organization model for multi-tenant isolation."""
    __tablename__ = "organizations"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)

    # Relationships
    users: Mapped[list["User"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    orders: Mapped[list["Order"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    jobs: Mapped[list["Job"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    production_history: Mapped[list["ProductionHistory"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    products: Mapped[list["Product"]] = relationship(back_populates="organization", cascade="all, delete-orphan")


class User(Base, TimestampMixin):
    """User model with organization membership."""
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=False
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False, default="seller")
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    organization: Mapped["Organization"] = relationship(back_populates="users")
    production_history_entries: Mapped[list["ProductionHistory"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Order(Base, TimestampMixin, SyncMixin):
    """Order model for customer orders."""
    __tablename__ = "orders"

    # Primary key
    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)

    # Organization isolation
    organization_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=False
    )

    # Customer information
    customer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    customer_phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Order details
    urgency: Mapped[str] = mapped_column(String(20), nullable=False, default="normal")  # normal, high, urgent
    delivery_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Financials
    subtotal: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    total: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    payment_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")  # pending, partial, paid, cancelled

    # Status
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        index=True
    )  # pending, accepted, in_design, in_production, ready, delivered, cancelled

    # Relationships
    organization: Mapped["Organization"] = relationship(back_populates="orders")
    jobs: Mapped[list["Job"]] = relationship(back_populates="order", cascade="all, delete-orphan")

    # Indexes
    __table_args__ = (
        Index("ix_orders_organization_status", "organization_id", "status"),
        Index("ix_orders_updated_at", "updated_at"),
        CheckConstraint("status IN ('pending', 'accepted', 'in_design', 'in_production', 'ready', 'delivered', 'cancelled')", name="check_order_status"),
        CheckConstraint("payment_status IN ('pending', 'partial', 'paid', 'cancelled')", name="check_payment_status"),
        CheckConstraint("urgency IN ('normal', 'high', 'urgent')", name="check_urgency"),
    )


class Job(Base, TimestampMixin, SyncMixin):
    """Job model for individual production jobs within an order."""
    __tablename__ = "jobs"

    # Primary key
    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)

    # Organization isolation
    organization_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=False
    )

    # Order relationship
    order_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        index=True,
        nullable=False
    )

    # Product information
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    material: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    dimensions: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Product/Variant/Price relationships
    product_id: Mapped[Optional[UUID]] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("products.id", ondelete="SET NULL"),
        index=True,
        nullable=True
    )
    variant_id: Mapped[Optional[UUID]] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("product_variants.id", ondelete="SET NULL"),
        index=True,
        nullable=True
    )
    price_list_id: Mapped[Optional[UUID]] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("price_lists.id", ondelete="SET NULL"),
        index=True,
        nullable=True
    )
    price_rule_id: Mapped[Optional[UUID]] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("price_rules.id", ondelete="SET NULL"),
        index=True,
        nullable=True
    )

    # Job type
    job_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="sticker_sheet"
    )  # sticker_sheet, individual_sticker, print, sublimation, custom_product

    # Quantity and pricing
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unit_price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    subtotal: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)

    # Status tracking
    production_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        index=True
    )  # pending, in_progress, completed, cancelled
    design_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending"
    )  # pending, in_progress, approved, cancelled

    # Production metrics
    print_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Additional data
    meta_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Relationships
    organization: Mapped["Organization"] = relationship(back_populates="jobs")
    order: Mapped["Order"] = relationship(back_populates="jobs")
    production_history: Mapped[list["ProductionHistory"]] = relationship(back_populates="job", cascade="all, delete-orphan")

    # Indexes and constraints
    __table_args__ = (
        Index("ix_jobs_organization_status", "organization_id", "production_status"),
        Index("ix_jobs_updated_at", "updated_at"),
        CheckConstraint("production_status IN ('pending', 'in_progress', 'completed', 'cancelled')", name="check_production_status"),
        CheckConstraint("design_status IN ('pending', 'in_progress', 'approved', 'cancelled')", name="check_design_status"),
        CheckConstraint("job_type IN ('sticker_sheet', 'individual_sticker', 'print', 'sublimation', 'custom_product')", name="check_job_type"),
        CheckConstraint("quantity > 0", name="check_quantity_positive"),
    )


class ProductionHistory(Base):
    """Production history model for tracking job status changes."""
    __tablename__ = "production_history"

    # Primary key
    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)

    # Organization isolation
    organization_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=False
    )

    # Job relationship
    job_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        index=True,
        nullable=False
    )

    # User who made the change
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )

    # Status change
    previous_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    new_status: Mapped[str] = mapped_column(String(20), nullable=False)

    # Additional information
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(back_populates="production_history")
    job: Mapped["Job"] = relationship(back_populates="production_history")
    user: Mapped[Optional["User"]] = relationship(back_populates="production_history_entries")

    # Indexes
    __table_args__ = ()


class Product(Base, TimestampMixin, SyncMixin):
    """Product model for catalog items."""
    __tablename__ = "products"

    # Primary key
    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)

    # Organization isolation
    organization_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=False
    )

    # Product information
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    image_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    base_price: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), nullable=True)

    # Status
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    organization: Mapped["Organization"] = relationship(back_populates="products")
    variants: Mapped[list["ProductVariant"]] = relationship(back_populates="product", cascade="all, delete-orphan")
    price_rules: Mapped[list["PriceRule"]] = relationship(back_populates="product", cascade="all, delete-orphan")

    # Indexes and constraints
    __table_args__ = (
        Index("ix_products_organization_active", "organization_id", "active"),
        Index("ix_products_category", "category"),
    )


class ProductVariant(Base, TimestampMixin, SyncMixin):
    """Product variant model for different sizes, materials, etc."""
    __tablename__ = "product_variants"

    # Primary key
    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)

    # Organization isolation
    organization_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=False
    )

    # Product relationship
    product_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        index=True,
        nullable=False
    )

    # Variant information
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    line: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    material: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    size: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    modality: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Status
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    organization: Mapped["Organization"] = relationship()
    product: Mapped["Product"] = relationship(back_populates="variants")
    price_rules: Mapped[list["PriceRule"]] = relationship(back_populates="variant", cascade="all, delete-orphan")

    # Indexes and constraints
    __table_args__ = (
        Index("ix_variants_product", "product_id"),
        Index("ix_variants_organization_active", "organization_id", "active"),
    )


class PriceList(Base, TimestampMixin, SyncMixin):
    """Price list model for different pricing tiers."""
    __tablename__ = "price_lists"

    # Primary key
    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)

    # Organization isolation
    organization_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=False
    )

    # Price list information
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    # Status
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    organization: Mapped["Organization"] = relationship()
    price_rules: Mapped[list["PriceRule"]] = relationship(back_populates="price_list", cascade="all, delete-orphan")

    # Indexes
    __table_args__ = (
        Index("ix_price_lists_organization_active", "organization_id", "active"),
    )


class PriceRule(Base, TimestampMixin, SyncMixin):
    """Price rule model for linking products/variants to prices."""
    __tablename__ = "price_rules"

    # Primary key
    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)

    # Organization isolation
    organization_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=False
    )

    # Product/Variant relationships
    product_id: Mapped[Optional[UUID]] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        index=True,
        nullable=True
    )
    variant_id: Mapped[Optional[UUID]] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("product_variants.id", ondelete="CASCADE"),
        index=True,
        nullable=True
    )
    price_list_id: Mapped[Optional[UUID]] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("price_lists.id", ondelete="CASCADE"),
        index=True,
        nullable=True
    )

    # Pricing information
    rule_name: Mapped[str] = mapped_column(String(200), nullable=False)
    max_quantity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    preparation_limit: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Price calculation (from desktop cost_rules structure)
    cost_mp_mode: Mapped[str] = mapped_column(String(20), default="percent", nullable=False)
    cost_mp_percent: Mapped[float] = mapped_column(Numeric(10, 2), default=0, nullable=False)
    cost_mp_fixed: Mapped[float] = mapped_column(Numeric(10, 2), default=0, nullable=False)
    cost_mp_unit: Mapped[float] = mapped_column(Numeric(10, 2), default=0, nullable=False)

    cost_mo_mode: Mapped[str] = mapped_column(String(20), default="percent", nullable=False)
    cost_mo_percent: Mapped[float] = mapped_column(Numeric(10, 2), default=0, nullable=False)
    cost_mo_fixed: Mapped[float] = mapped_column(Numeric(10, 2), default=0, nullable=False)
    cost_mo_unit: Mapped[float] = mapped_column(Numeric(10, 2), default=0, nullable=False)

    cost_cf_mode: Mapped[str] = mapped_column(String(20), default="percent", nullable=False)
    cost_cf_percent: Mapped[float] = mapped_column(Numeric(10, 2), default=0, nullable=False)
    cost_cf_fixed: Mapped[float] = mapped_column(Numeric(10, 2), default=0, nullable=False)
    cost_cf_unit: Mapped[float] = mapped_column(Numeric(10, 2), default=0, nullable=False)

    components_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Status
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    organization: Mapped["Organization"] = relationship()
    product: Mapped[Optional["Product"]] = relationship(back_populates="price_rules")
    variant: Mapped[Optional["ProductVariant"]] = relationship(back_populates="price_rules")
    price_list: Mapped[Optional["PriceList"]] = relationship(back_populates="price_rules")

    # Indexes and constraints
    __table_args__ = (
        Index("ix_price_rules_match", "product_id", "variant_id", "price_list_id", "active"),
        Index("ix_price_rules_organization", "organization_id"),
    )
