import os
from coolpc.db.session import get_engine, get_session_factory
from coolpc.db.models import Base, Category


def test_get_engine_and_session_roundtrip(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("COOLPC_DB_PATH", str(db_path))
    engine = get_engine()
    Base.metadata.create_all(engine)
    Session = get_session_factory(engine)
    with Session() as session:
        session.add(Category(name="測試分類"))
        session.commit()
    with Session() as session:
        assert session.query(Category).count() == 1
    assert db_path.exists()
