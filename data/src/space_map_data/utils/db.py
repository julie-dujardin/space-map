"""Shared SQLite database connection and session management.

Usage in __main__::

    with session_scope(create_db=True):
        ingest(...)

Usage anywhere else::

    from space_map_data.utils.db import get_session
    session = get_session()
"""

import shutil
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from space_map_data.models.object import Base
from space_map_data.utils.paths import DB_DIR, DB_FILE

_session: Session | None = None


def _make_engine(db_path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))
        conn.execute(text("PRAGMA synchronous=NORMAL"))
        conn.commit()
    return engine


@contextmanager
def session_scope(create_db: bool = False) -> Generator[Session]:
    """Open a managed DB session, accessible globally via `get_session()`.

    Args:
        create_db: When True, create all tables (used by ingest pipeline).
                   When False, the DB file must already exist.
    """
    global _session

    if create_db:
        if DB_DIR.exists():
            shutil.rmtree(DB_DIR)
        DB_DIR.mkdir(parents=True, exist_ok=True)
    elif not DB_FILE.exists():
        raise FileNotFoundError(f"Database not found at {DB_FILE} — run ingest first")

    engine = _make_engine(DB_FILE)
    if create_db:
        Base.metadata.create_all(engine)

    _session = Session(engine)
    yield _session
    _session.close()
    _session = None
    engine.dispose()


def get_session() -> Session:
    """Return the active session. Raises if not inside a `session_scope`."""
    if _session is None:
        raise RuntimeError(
            "No active session — wrap your entry point in session_scope()"
        )
    return _session
