"""drop unused products.first_seen_at column

Revision ID: 0007_drop_product_first_seen_at
Revises: 0006_drop_last_change_columns
Create Date: 2026-09-04 00:00:00.000000

Why this is being dropped
--------------------------
``ingest_product()`` always set ``first_seen_at`` and ``created_at`` to the
exact same value (the scrape's ``fetched_at`` timestamp) whenever a new
product row was created, and nothing ever updated ``first_seen_at``
afterward -- across the whole codebase and every test fixture the two
columns were always equal. ``created_at`` is kept as the single source of
truth for "when this product was first seen"; removed at the user's
explicit request. Public API/pages that displayed "第一次出現" now read
``created_at`` instead (see ``coolpc.public_api.schemas.ProductDetail`` and
``coolpc.public_api.templates.product_detail``).

Note this only touches ``products.first_seen_at``. ``product_names`` has
its own, unrelated ``first_seen_at`` column (when a given historical name
was first seen) which is untouched -- it is not always equal to that name's
row's other timestamps and is still read by the compare/product-detail
pages.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007_drop_product_first_seen_at"
down_revision: Union[str, Sequence[str], None] = "0006_drop_last_change_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("products") as batch_op:
        batch_op.drop_column("first_seen_at")


def downgrade() -> None:
    with op.batch_alter_table("products") as batch_op:
        batch_op.add_column(sa.Column("first_seen_at", sa.DateTime(), nullable=True))
