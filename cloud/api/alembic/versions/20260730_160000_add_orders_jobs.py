"""Add orders, jobs, and production_history tables.

Assumes organizations and users tables already exist from previous API version.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '20260730_160000'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create orders table
    op.create_table(
        'orders',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('customer_name', sa.String(length=200), nullable=False),
        sa.Column('customer_phone', sa.String(length=50), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('urgency', sa.String(length=20), nullable=False),
        sa.Column('delivery_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('subtotal', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('total', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('payment_status', sa.String(length=20), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint("status IN ('pending', 'accepted', 'in_design', 'in_production', 'ready', 'delivered', 'cancelled')", name='check_order_status'),
        sa.CheckConstraint("payment_status IN ('pending', 'partial', 'paid', 'cancelled')", name='check_payment_status'),
        sa.CheckConstraint("urgency IN ('normal', 'high', 'urgent')", name='check_urgency')
    )
    op.create_index(op.f('ix_orders_organization_id'), 'orders', ['organization_id'], unique=False)
    op.create_index(op.f('ix_orders_status'), 'orders', ['status'], unique=False)
    op.create_index(op.f('ix_orders_updated_at'), 'orders', ['updated_at'], unique=False)
    op.create_index('ix_orders_organization_status', 'orders', ['organization_id', 'status'], unique=False)
    op.create_index(op.f('ix_orders_deleted_at'), 'orders', ['deleted_at'], unique=False)

    # Create jobs table
    op.create_table(
        'jobs',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('order_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('product_name', sa.String(length=200), nullable=False),
        sa.Column('material', sa.String(length=100), nullable=True),
        sa.Column('dimensions', sa.String(length=100), nullable=True),
        sa.Column('job_type', sa.String(length=50), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('unit_price', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('subtotal', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('production_status', sa.String(length=20), nullable=False),
        sa.Column('design_status', sa.String(length=20), nullable=False),
        sa.Column('print_count', sa.Integer(), nullable=False),
        sa.Column('error_count', sa.Integer(), nullable=False),
        sa.Column('meta_data', postgresql.JSON(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint("production_status IN ('pending', 'in_progress', 'completed', 'cancelled')", name='check_production_status'),
        sa.CheckConstraint("design_status IN ('pending', 'in_progress', 'approved', 'cancelled')", name='check_design_status'),
        sa.CheckConstraint("job_type IN ('sticker_sheet', 'individual_sticker', 'print', 'sublimation', 'custom_product')", name='check_job_type'),
        sa.CheckConstraint('quantity > 0', name='check_quantity_positive')
    )
    op.create_index(op.f('ix_jobs_organization_id'), 'jobs', ['organization_id'], unique=False)
    op.create_index(op.f('ix_jobs_order_id'), 'jobs', ['order_id'], unique=False)
    op.create_index(op.f('ix_jobs_production_status'), 'jobs', ['production_status'], unique=False)
    op.create_index(op.f('ix_jobs_updated_at'), 'jobs', ['updated_at'], unique=False)
    op.create_index('ix_jobs_organization_status', 'jobs', ['organization_id', 'production_status'], unique=False)
    op.create_index(op.f('ix_jobs_deleted_at'), 'jobs', ['deleted_at'], unique=False)

    # Create production_history table
    op.create_table(
        'production_history',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('job_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('previous_status', sa.String(length=20), nullable=True),
        sa.Column('new_status', sa.String(length=20), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_production_history_job_id'), 'production_history', ['job_id'], unique=False)
    op.create_index(op.f('ix_production_history_created_at'), 'production_history', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_production_history_created_at'), table_name='production_history')
    op.drop_index(op.f('ix_production_history_job_id'), table_name='production_history')
    op.drop_table('production_history')

    op.drop_index('ix_jobs_deleted_at', table_name='jobs')
    op.drop_index('ix_jobs_organization_status', table_name='jobs')
    op.drop_index(op.f('ix_jobs_updated_at'), table_name='jobs')
    op.drop_index(op.f('ix_jobs_production_status'), table_name='jobs')
    op.drop_index(op.f('ix_jobs_order_id'), table_name='jobs')
    op.drop_index(op.f('ix_jobs_organization_id'), table_name='jobs')
    op.drop_table('jobs')

    op.drop_index('ix_orders_deleted_at', table_name='orders')
    op.drop_index('ix_orders_organization_status', table_name='orders')
    op.drop_index(op.f('ix_orders_updated_at'), table_name='orders')
    op.drop_index(op.f('ix_orders_status'), table_name='orders')
    op.drop_index(op.f('ix_orders_organization_id'), table_name='orders')
    op.drop_table('orders')
