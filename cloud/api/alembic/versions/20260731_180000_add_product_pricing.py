"""Add products, variants, price lists, and price rules tables.

Also adds product/price relationship columns to jobs table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '20260731_180000'
down_revision: Union[str, None] = '20260730_160000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add product/price relationship columns to jobs table
    op.add_column('jobs', sa.Column('product_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('jobs', sa.Column('variant_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('jobs', sa.Column('price_list_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('jobs', sa.Column('price_rule_id', postgresql.UUID(as_uuid=True), nullable=True))

    op.create_foreign_key('fk_jobs_product_id', 'jobs', 'products', ['product_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_jobs_variant_id', 'jobs', 'product_variants', ['variant_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_jobs_price_list_id', 'jobs', 'price_lists', ['price_list_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_jobs_price_rule_id', 'jobs', 'price_rules', ['price_rule_id'], ['id'], ondelete='SET NULL')

    op.create_index('ix_jobs_product_id', 'jobs', ['product_id'], unique=False)
    op.create_index('ix_jobs_variant_id', 'jobs', ['variant_id'], unique=False)
    op.create_index('ix_jobs_price_list_id', 'jobs', ['price_list_id'], unique=False)
    op.create_index('ix_jobs_price_rule_id', 'jobs', ['price_rule_id'], unique=False)

    # Create products table
    op.create_table(
        'products',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('code', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('category', sa.String(length=100), nullable=True),
        sa.Column('image_path', sa.String(length=500), nullable=True),
        sa.Column('base_price', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code')
    )
    op.create_index(op.f('ix_products_organization_id'), 'products', ['organization_id'], unique=False)
    op.create_index(op.f('ix_products_code'), 'products', ['code'], unique=True)
    op.create_index('ix_products_organization_active', 'products', ['organization_id', 'active'], unique=False)
    op.create_index('ix_products_category', 'products', ['category'], unique=False)
    op.create_index(op.f('ix_products_deleted_at'), 'products', ['deleted_at'], unique=False)

    # Create product_variants table
    op.create_table(
        'product_variants',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('product_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('code', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('line', sa.String(length=100), nullable=True),
        sa.Column('material', sa.String(length=100), nullable=True),
        sa.Column('size', sa.String(length=100), nullable=True),
        sa.Column('modality', sa.String(length=100), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code')
    )
    op.create_index(op.f('ix_product_variants_organization_id'), 'product_variants', ['organization_id'], unique=False)
    op.create_index(op.f('ix_product_variants_product_id'), 'product_variants', ['product_id'], unique=False)
    op.create_index(op.f('ix_product_variants_code'), 'product_variants', ['code'], unique=True)
    op.create_index('ix_variants_product', 'product_variants', ['product_id'], unique=False)
    op.create_index('ix_variants_organization_active', 'product_variants', ['organization_id', 'active'], unique=False)
    op.create_index(op.f('ix_product_variants_deleted_at'), 'product_variants', ['deleted_at'], unique=False)

    # Create price_lists table
    op.create_table(
        'price_lists',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('code', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code')
    )
    op.create_index(op.f('ix_price_lists_organization_id'), 'price_lists', ['organization_id'], unique=False)
    op.create_index(op.f('ix_price_lists_code'), 'price_lists', ['code'], unique=True)
    op.create_index('ix_price_lists_organization_active', 'price_lists', ['organization_id', 'active'], unique=False)
    op.create_index(op.f('ix_price_lists_deleted_at'), 'price_lists', ['deleted_at'], unique=False)

    # Create price_rules table
    op.create_table(
        'price_rules',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('product_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('variant_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('price_list_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('rule_name', sa.String(length=200), nullable=False),
        sa.Column('max_quantity', sa.Integer(), nullable=True),
        sa.Column('priority', sa.Integer(), nullable=False),
        sa.Column('preparation_limit', sa.Integer(), nullable=True),
        sa.Column('cost_mp_mode', sa.String(length=20), nullable=False),
        sa.Column('cost_mp_percent', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('cost_mp_fixed', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('cost_mp_unit', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('cost_mo_mode', sa.String(length=20), nullable=False),
        sa.Column('cost_mo_percent', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('cost_mo_fixed', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('cost_mo_unit', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('cost_cf_mode', sa.String(length=20), nullable=False),
        sa.Column('cost_cf_percent', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('cost_cf_fixed', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('cost_cf_unit', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('components_json', sa.Text(), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['variant_id'], ['product_variants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['price_list_id'], ['price_lists.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_price_rules_organization_id'), 'price_rules', ['organization_id'], unique=False)
    op.create_index(op.f('ix_price_rules_product_id'), 'price_rules', ['product_id'], unique=False)
    op.create_index(op.f('ix_price_rules_variant_id'), 'price_rules', ['variant_id'], unique=False)
    op.create_index(op.f('ix_price_rules_price_list_id'), 'price_rules', ['price_list_id'], unique=False)
    op.create_index('ix_price_rules_match', 'price_rules', ['product_id', 'variant_id', 'price_list_id', 'active'], unique=False)
    op.create_index('ix_price_rules_organization', 'price_rules', ['organization_id'], unique=False)
    op.create_index(op.f('ix_price_rules_deleted_at'), 'price_rules', ['deleted_at'], unique=False)


def downgrade() -> None:
    # Drop price_rules table
    op.drop_index(op.f('ix_price_rules_deleted_at'), table_name='price_rules')
    op.drop_index('ix_price_rules_organization', table_name='price_rules')
    op.drop_index('ix_price_rules_match', table_name='price_rules')
    op.drop_index(op.f('ix_price_rules_price_list_id'), table_name='price_rules')
    op.drop_index(op.f('ix_price_rules_variant_id'), table_name='price_rules')
    op.drop_index(op.f('ix_price_rules_product_id'), table_name='price_rules')
    op.drop_index(op.f('ix_price_rules_organization_id'), table_name='price_rules')
    op.drop_table('price_rules')

    # Drop price_lists table
    op.drop_index(op.f('ix_price_lists_deleted_at'), table_name='price_lists')
    op.drop_index('ix_price_lists_organization_active', table_name='price_lists')
    op.drop_index(op.f('ix_price_lists_code'), table_name='price_lists')
    op.drop_index(op.f('ix_price_lists_organization_id'), table_name='price_lists')
    op.drop_table('price_lists')

    # Drop product_variants table
    op.drop_index(op.f('ix_product_variants_deleted_at'), table_name='product_variants')
    op.drop_index('ix_variants_organization_active', table_name='product_variants')
    op.drop_index('ix_variants_product', table_name='product_variants')
    op.drop_index(op.f('ix_product_variants_code'), table_name='product_variants')
    op.drop_index(op.f('ix_product_variants_product_id'), table_name='product_variants')
    op.drop_index(op.f('ix_product_variants_organization_id'), table_name='product_variants')
    op.drop_table('product_variants')

    # Drop products table
    op.drop_index(op.f('ix_products_deleted_at'), table_name='products')
    op.drop_index('ix_products_category', table_name='products')
    op.drop_index('ix_products_organization_active', table_name='products')
    op.drop_index(op.f('ix_products_code'), table_name='products')
    op.drop_index(op.f('ix_products_organization_id'), table_name='products')
    op.drop_table('products')

    # Drop product/price relationship columns from jobs table
    op.drop_index('ix_jobs_price_rule_id', table_name='jobs')
    op.drop_index('ix_jobs_price_list_id', table_name='jobs')
    op.drop_index('ix_jobs_variant_id', table_name='jobs')
    op.drop_index('ix_jobs_product_id', table_name='jobs')
    op.drop_constraint('fk_jobs_price_rule_id', 'jobs')
    op.drop_constraint('fk_jobs_price_list_id', 'jobs')
    op.drop_constraint('fk_jobs_variant_id', 'jobs')
    op.drop_constraint('fk_jobs_product_id', 'jobs')
    op.drop_column('jobs', 'price_rule_id')
    op.drop_column('jobs', 'price_list_id')
    op.drop_column('jobs', 'variant_id')
    op.drop_column('jobs', 'product_id')
