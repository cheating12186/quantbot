"""SQLAlchemy engine/session setup, safe for Streamlit's multiple threads."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from database.models import Base


def _connect_args(url: str) -> dict:
    if url.startswith("sqlite"):
        # Streamlit runs multiple threads against one engine.
        return {"check_same_thread": False}
    if url.startswith(("postgresql://", "postgres://", "postgresql+psycopg://", "postgresql+psycopg2://")):
        # Supabase pooler (PgBouncer, port 6543, transaction pooling) multiplexes
        # server connections, so server-side prepared statements are unreliable and
        # surface as intermittent "prepared statement does not exist" errors.
        # psycopg disables prepared statements with prepare_threshold=None.
        return {"prepare_threshold": None} if "psycopg2" not in url else {}
    return {}


class Database:
    def __init__(self, url: str):
        if url.startswith("sqlite:///"):
            path = url.removeprefix("sqlite:///")
            if path != ":memory:":
                Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(url, connect_args=_connect_args(url), pool_pre_ping=True)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False, class_=Session)
        Base.metadata.create_all(self.engine)
        # Lightweight additive migration for early MVP databases. Complex future
        # migrations should move to Alembic; destructive changes are never implicit.
        if url.startswith("sqlite"):
            with self.engine.begin() as connection:
                columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(positions)").all()}
                if columns and "entry_fees" not in columns:
                    connection.exec_driver_sql("ALTER TABLE positions ADD COLUMN entry_fees FLOAT DEFAULT 0")

    @contextmanager
    def session(self):
        session = self.sessions()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
