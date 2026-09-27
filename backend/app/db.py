"""SQLAlchemy engine and session management.

SQLite today; the URL in Settings is the only thing that needs to change to move
to PostgreSQL (the `connect_args` below is the sole SQLite-specific line).
"""
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()

_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create tables and seed the single professor row."""
    from app import models  # noqa: F401  (registers mappers)

    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        if db.get(models.Professor, 1) is None:
            db.add(models.Professor(id=1, name="Professor", email=""))
            db.commit()
