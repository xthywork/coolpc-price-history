import datetime
import subprocess, sys, os
from sqlalchemy import text
from coolpc.db.session import get_engine, get_session_factory
from coolpc.db.models import Base, Category, Subcategory, Product, ProductName


def _upgrade_head(db_path):
    env = os.environ.copy()
    env["COOLPC_DB_PATH"] = str(db_path)
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True, env=env)


def test_fts_search_finds_product_by_substring(tmp_path, monkeypatch):
    db_path = tmp_path / "fts.db"
    monkeypatch.setenv("COOLPC_DB_PATH", str(db_path))
    _upgrade_head(db_path)
    engine = get_engine(str(db_path))
    Session = get_session_factory(engine)
    now = datetime.datetime(2026, 2, 1)
    with Session() as session:
        cat = Category(name="固態硬碟")
        sub = Subcategory(name="NAS碟", category=cat)
        session.add_all([cat, sub])
        session.flush()
        p = Product(category_id=cat.id, subcategory_id=sub.id,
                     current_name="Synology HAT3300 4TB PLUS系列(3.5吋/5400轉/三年保固)【限搭NAS主機】",
                     current_price=6890, is_active=True, first_seen_at=now,
                     last_seen_at=now, created_at=now)
        session.add(p)
        session.flush()
        session.add(ProductName(product_id=p.id, name=p.current_name,
                                 first_seen_at=now, last_seen_at=now))
        session.commit()

        rows = session.execute(
            text("SELECT product_id FROM products_fts WHERE products_fts MATCH :q"),
            {"q": "限搭"},
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == p.id


def _fts_row_count(session, product_id, source_name):
    return session.execute(
        text(
            "SELECT count(*) FROM products_fts "
            "WHERE product_id = :pid AND source_name = :n"
        ),
        {"pid": product_id, "n": source_name},
    ).scalar()


def test_fts_delete_and_update_sync_rows(tmp_path, monkeypatch):
    """DELETE must remove all products_fts rows (whole-text + bigrams) for a
    product_names row, and UPDATE must remove the old name's rows while
    inserting the new name's rows exactly once (no leftover duplication)."""
    db_path = tmp_path / "fts_sync.db"
    monkeypatch.setenv("COOLPC_DB_PATH", str(db_path))
    _upgrade_head(db_path)
    engine = get_engine(str(db_path))
    Session = get_session_factory(engine)
    now = datetime.datetime(2026, 2, 1)
    old_name = "Synology HAT3300 4TB PLUS系列(3.5吋/5400轉/三年保固)【限搭NAS主機】"
    new_name = "Synology HAT3300 4TB PLUS系列(3.5吋/5400轉/三年保固)【換購優惠版】"
    control_name = "控制組對照名稱ABC123"

    with Session() as session:
        cat = Category(name="固態硬碟")
        sub = Subcategory(name="NAS碟", category=cat)
        session.add_all([cat, sub])
        session.flush()

        p = Product(category_id=cat.id, subcategory_id=sub.id,
                     current_name=old_name, current_price=6890, is_active=True,
                     first_seen_at=now, last_seen_at=now, created_at=now)
        session.add(p)
        session.flush()
        pn = ProductName(product_id=p.id, name=old_name,
                          first_seen_at=now, last_seen_at=now)
        session.add(pn)
        session.commit()

        # sanity: the INSERT trigger populated rows (whole-text + bigrams)
        assert _fts_row_count(session, p.id, old_name) == len(old_name)

        # --- DELETE path: removing the product_names row must remove ALL
        # its products_fts rows (whole-text row + every bigram row), with
        # no stale rows left behind, and MATCH must no longer find it.
        session.delete(pn)
        session.commit()

        assert _fts_row_count(session, p.id, old_name) == 0
        no_match = session.execute(
            text("SELECT product_id FROM products_fts WHERE products_fts MATCH :q"),
            {"q": "限搭"},
        ).fetchall()
        assert no_match == []

        # --- UPDATE path: rename via a fresh product_names row, then
        # update its name. Old name's rows must be fully gone, new name
        # must be findable by MATCH, and the new name's row count must
        # equal what indexing that name from scratch produces (validated
        # below against an independent control product/name), proving no
        # duplication from lingering old-name rows.
        pn2 = ProductName(product_id=p.id, name=old_name,
                           first_seen_at=now, last_seen_at=now)
        session.add(pn2)
        session.commit()

        pn2.name = new_name
        session.commit()

        assert _fts_row_count(session, p.id, old_name) == 0

        rows = session.execute(
            text("SELECT product_id FROM products_fts WHERE products_fts MATCH :q"),
            {"q": "換購"},
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == p.id

        # Control: a completely independent, freshly-inserted product_names
        # row establishes what "a fresh INSERT of this name alone" produces
        # in products_fts (1 whole-text row + one row per character bigram).
        cat2 = Category(name="固態硬碟-對照")
        sub2 = Subcategory(name="NAS碟-對照", category=cat2)
        session.add_all([cat2, sub2])
        session.flush()
        p2 = Product(category_id=cat2.id, subcategory_id=sub2.id,
                      current_name=control_name, current_price=1000,
                      is_active=True, first_seen_at=now, last_seen_at=now,
                      created_at=now)
        session.add(p2)
        session.flush()
        session.add(ProductName(product_id=p2.id, name=control_name,
                                 first_seen_at=now, last_seen_at=now))
        session.commit()

        control_count = _fts_row_count(session, p2.id, control_name)
        assert control_count == len(control_name)

        # The updated product's row count for its new name must match the
        # same fresh-insert invariant (length-derived, same as control) --
        # i.e. exactly what a fresh insert of new_name alone would produce,
        # with no extra rows surviving from the deleted old_name.
        updated_count = _fts_row_count(session, p.id, new_name)
        assert updated_count == len(new_name)
