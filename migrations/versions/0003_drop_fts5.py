"""drop unused products_fts index

Revision ID: 0003_drop_fts5
Revises: 0002_fts5
Create Date: 2026-09-03 00:00:00.000000

Why this is being dropped
--------------------------
The ``products_fts`` FTS5 virtual table and its triggers (built in Task 4,
performance-fixed in Task 28) are confirmed dead code: the public search
feature deliberately uses plain ``LIKE`` matching (see
``coolpc.search.service.search_products``), and nothing under ``src/``
ever queries ``products_fts``.

Worse, it is now confirmed to be subtly wrong after any merge:
``merge_products`` (Task 15) re-points ``ProductName.product_id`` to the
target product without changing ``ProductName.name``. The ``AFTER UPDATE``
trigger's ``WHEN OLD.name IS NOT NEW.name`` guard (added in Task 28 to fix
a real performance regression) means this kind of update never fires the
trigger, so ``products_fts.product_id`` keeps pointing at the merged-away
source product forever after a merge. It has not caused a live bug only
because nothing reads the table today -- but it is maintenance-hazard dead
weight that "looks maintained" while quietly being incorrect.

Rather than fix the trigger to also handle product_id-only reassignment,
this migration removes the unused feature outright.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_drop_fts5"
down_revision: Union[str, Sequence[str], None] = "0002_fts5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("DROP TRIGGER IF EXISTS product_names_au")
    op.execute("DROP TRIGGER IF EXISTS product_names_ad")
    op.execute("DROP TRIGGER IF EXISTS product_names_ai")
    op.execute("DROP TABLE IF EXISTS products_fts")


def downgrade() -> None:
    """Downgrade schema.

    Recreating the exact original FTS5 table/triggers here would require
    duplicating 0002_fts5's schema; since this is a deliberate removal of
    an unused (and subtly incorrect-after-merge) feature -- not a mistake
    being fixed forward -- downgrade is intentionally a no-op rather than
    resurrecting dead code.
    """
    pass
