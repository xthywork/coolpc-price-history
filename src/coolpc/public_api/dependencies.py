from __future__ import annotations
from collections.abc import Iterator
from sqlalchemy.orm import Session
from coolpc.db.session import get_engine, get_session_factory

_session_factory = None


def get_session() -> Iterator[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = get_session_factory(get_engine())
    session = _session_factory()
    try:
        yield session
    finally:
        session.close()
