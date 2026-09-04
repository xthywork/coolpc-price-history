"""add optional sort_order override to categories

Revision ID: 0005_category_sort_order
Revises: 0004_category_display_names
Create Date: 2026-09-06 00:00:00.000000

Why this exists
----------------
Same rationale as display_name (migration 0004): purely a display concern,
never read by the ingest/matching path. NULL means "no preference, sort
after every category that has one, by name." Only Category gets an order
override (not Subcategory) — subcategories within a category still sort
alphabetically by name, which is all that was asked for.
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_category_sort_order"
down_revision = "0004_category_display_names"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("categories", sa.Column("sort_order", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("categories", "sort_order")
