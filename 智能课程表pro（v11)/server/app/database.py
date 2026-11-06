"""Database setup and request-scoped sessions."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def sqlite_url(path: str | Path) -> str:
    resolved = Path(path).resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{resolved.as_posix()}"


def build_engine(database_url: str):
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, connect_args=connect_args, future=True)


def build_session_factory(database_url: str):
    engine = build_engine(database_url)
    return engine, sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def run_migrations(database_url: str, project_root: Path | None = None) -> None:
    root = project_root or Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")


def session_scope(factory: sessionmaker) -> Generator[Session, None, None]:
    session = factory()
    try:
        yield session
    finally:
        session.close()
