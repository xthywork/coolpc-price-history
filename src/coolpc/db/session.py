import os
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session

DEFAULT_DB_PATH = "data/coolpc.db"


def get_db_path() -> str:
    return os.environ.get("COOLPC_DB_PATH", DEFAULT_DB_PATH)


def get_engine(db_path: str | None = None) -> Engine:
    path = db_path or get_db_path()
    engine = create_engine(f"sqlite:///{path}")

    # I1: SQLite 預設的 rollback-journal 模式下，寫入交易會把所有讀取者都
    # 擋住。ingest_snapshot 一次抓取的整個交易可能要花上數秒到數十秒，而
    # scraper、public 網站、admin 網站是三個各自獨立的行程共用同一個 DB
    # 檔案，所以排程抓取時，公開網站有機會回傳「database is locked」給真正
    # 的使用者。開啟 WAL 模式讓讀取者在寫入交易進行時仍可並行讀取；
    # busy_timeout 是保底措施；foreign_keys 預設在 SQLite 是關閉的，開啟它
    # 讓 schema 上的 FK 限制真正生效，而不只是文件上的裝飾。
    #
    # ":memory:" 資料庫不支援 WAL（PRAGMA journal_mode=WAL 對它是無害的
    # no-op，實測會靜靜地維持在 "memory" 模式，不會拋錯），所以這裡仍然
    # 對它套用同一組 pragma，busy_timeout/foreign_keys 一樣有意義。
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def get_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine)
