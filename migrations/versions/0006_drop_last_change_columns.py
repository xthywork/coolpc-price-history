"""drop unused last_change_amount / last_change_percent columns from products

Revision ID: 0006_drop_last_change_columns
Revises: 0005_category_sort_order
Create Date: 2026-09-04 00:00:00.000000

Why this is being dropped
--------------------------
These two columns were only ever used to power the SearchFilters
``recent_change`` / ``min_change_percent`` / ``max_change_percent`` query
params (see ``coolpc.search.service.search_products``), which were never
wired up in any page's UI -- dead API surface. The user-facing 漲跌 figures
shown on the product detail / compare pages come from
``compute_product_stats()``, computed live from ``price_history`` on every
request, and never read these columns. Removed at the user's explicit
request; the search filters and the ingest-time writes to these columns
are removed in the same change (see ``coolpc.search.service`` and
``coolpc.ingest.service``).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006_drop_last_change_columns"
down_revision: Union[str, Sequence[str], None] = "0005_category_sort_order"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("products") as batch_op:
        batch_op.drop_column("last_change_amount")
        batch_op.drop_column("last_change_percent")


def downgrade() -> None:
    with op.batch_alter_table("products") as batch_op:
        batch_op.add_column(sa.Column("last_change_amount", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("last_change_percent", sa.Float(), nullable=True))
