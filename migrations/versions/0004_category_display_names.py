"""add optional display_name override to categories and subcategories

Revision ID: 0004_category_display_names
Revises: 0003_drop_fts5
Create Date: 2026-09-05 00:00:00.000000

Why this exists
----------------
``Category.name`` / ``Subcategory.name`` are matched exactly against the
live site's HTML on every scrape (see ``get_or_create_category`` /
``get_or_create_subcategory`` in ``coolpc.ingest.service``) — renaming them
directly would break that matching and cause a duplicate row with the
original scraped name on the next scrape. ``display_name`` is a purely
optional, admin-set override for what gets shown to a human; it is never
read by the ingest/matching path. NULL means "show the original name."
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_category_display_names"
down_revision = "0003_drop_fts5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("categories", sa.Column("display_name", sa.String(), nullable=True))
    op.add_column("subcategories", sa.Column("display_name", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("subcategories", "display_name")
    op.drop_column("categories", "display_name")
