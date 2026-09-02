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
