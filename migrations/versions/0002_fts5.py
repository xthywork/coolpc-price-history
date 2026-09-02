"""fts5 for product_names

Revision ID: 0002_fts5
Revises: 53b4bb1e5ed2
Create Date: 2026-09-02 00:00:00.000000

Note on tokenizer choice
-------------------------
SQLite FTS5's built-in tokenizers do not support CJK substring search out of
the box:

- ``unicode61`` glues any run of consecutive "letter"/"number" category
  characters into a single token, with no word-boundary detection for
  scripts like Chinese that don't use spaces. A run such as
  ``限搭NAS主機`` becomes ONE token, so a query for a short substring like
  ``限搭`` (an exact-token MATCH) never finds it.
- ``trigram`` splits content into overlapping 3-character windows, but a
  MATCH query shorter than 3 characters produces zero trigrams and always
  returns no rows -- so it can't satisfy short (1-2 char) CJK queries
  either.

To support arbitrary CJK substring search (as required by the public
search feature, Task 15) without a custom C tokenizer, this migration
indexes each product name twice: once as the whole string (so normal
word/prefix search on Latin/number tokens still works), and once as every
overlapping 2-character bigram of the string (so any 2-character CJK
substring query -- which unicode61 tokenizes as a single token equal to
itself -- has a matching indexed token). A ``source_name`` UNINDEXED
column tracks which ``product_names.name`` each row came from so the
DELETE/UPDATE triggers can clean up all rows (whole-text + bigrams) for a
given name without having to recompute the bigram expansion.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_fts5"
down_revision: Union[str, Sequence[str], None] = "53b4bb1e5ed2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_BIGRAM_INSERT = """
    INSERT INTO products_fts(product_id, source_name, name)
    WITH RECURSIVE seq(i) AS (
        SELECT 1
        UNION ALL
        SELECT i + 1 FROM seq WHERE i < LENGTH({name}) - 1
    )
    SELECT {product_id}, {name}, substr({name}, i, 2)
    FROM seq
    WHERE LENGTH({name}) >= 2;
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
        CREATE VIRTUAL TABLE products_fts USING fts5(
            product_id UNINDEXED, source_name UNINDEXED, name, tokenize='unicode61'
        )
    """)

    op.execute(f"""
        CREATE TRIGGER product_names_ai AFTER INSERT ON product_names BEGIN
            INSERT INTO products_fts(product_id, source_name, name)
            VALUES (new.product_id, new.name, new.name);
            {_BIGRAM_INSERT.format(name="new.name", product_id="new.product_id")}
        END
    """)
    op.execute("""
        CREATE TRIGGER product_names_ad AFTER DELETE ON product_names BEGIN
            DELETE FROM products_fts WHERE product_id = old.product_id AND source_name = old.name;
        END
    """)
    op.execute(f"""
        CREATE TRIGGER product_names_au AFTER UPDATE ON product_names BEGIN
            DELETE FROM products_fts WHERE product_id = old.product_id AND source_name = old.name;
            INSERT INTO products_fts(product_id, source_name, name)
            VALUES (new.product_id, new.name, new.name);
            {_BIGRAM_INSERT.format(name="new.name", product_id="new.product_id")}
        END
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER IF EXISTS product_names_au")
    op.execute("DROP TRIGGER IF EXISTS product_names_ad")
    op.execute("DROP TRIGGER IF EXISTS product_names_ai")
    op.execute("DROP TABLE IF EXISTS products_fts")
