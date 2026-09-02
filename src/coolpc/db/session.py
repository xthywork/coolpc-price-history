import os
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session

DEFAULT_DB_PATH = "data/coolpc.db"


def get_db_path() -> str:
    return os.environ.get("COOLPC_DB_PATH", DEFAULT_DB_PATH)


def get_engine(db_path: str | None = None) -> Engine:
    path = db_path or get_db_path()
    return create_engine(f"sqlite:///{path}")


def get_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine)
