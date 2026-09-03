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


def test_get_engine_enables_wal_mode(tmp_path, monkeypatch):
    """I1: 排程抓取一次交易可能跑好幾秒到幾十秒，SQLite 預設的 rollback
    journal 模式下寫入者會擋住所有讀取者。get_engine() 回傳的引擎必須開啟
    WAL 模式，讓讀取者在寫入交易進行中仍可並行讀取。"""
    db_path = tmp_path / "wal.db"
    monkeypatch.setenv("COOLPC_DB_PATH", str(db_path))
    engine = get_engine()
    Base.metadata.create_all(engine)

    with engine.connect() as conn:
        mode = conn.exec_driver_sql("PRAGMA journal_mode").scalar()
        assert mode is not None and mode.lower() == "wal"

        fk = conn.exec_driver_sql("PRAGMA foreign_keys").scalar()
        assert fk == 1


def test_get_engine_pragma_listener_does_not_break_in_memory_engine():
    """I1 的注意事項：connect 事件監聽器會對每一個新連線觸發，包含測試套件
    大量使用的 :memory: 引擎。:memory: 資料庫不支援 WAL，必須確認套用這組
    pragma 不會讓 :memory: 引擎報錯或無法使用（busy_timeout/foreign_keys
    仍應正常設定）。"""
    engine = get_engine(":memory:")
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        # 不應拋例外；:memory: 不支援 WAL，落回其他模式也是可接受的行為
        mode = conn.exec_driver_sql("PRAGMA journal_mode").scalar()
        assert mode is not None
        fk = conn.exec_driver_sql("PRAGMA foreign_keys").scalar()
        assert fk == 1
        conn.exec_driver_sql("INSERT INTO categories (name) VALUES ('x')")
