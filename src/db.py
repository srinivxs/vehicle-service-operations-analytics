"""Database connection helpers shared by the loader and the SQL report runner.

Credentials are read from environment variables (populated from ``.env`` through
python-dotenv). Nothing is hardcoded; missing variables fail fast with a clear message.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import psycopg
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SQL_DIR = PROJECT_ROOT / "sql"
DB_SCHEMA = "service_ops"
REQUIRED_VARS = ("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD")


@dataclass(frozen=True)
class DbSettings:
    """Connection settings; ``password`` is excluded from ``repr`` so it never reaches logs."""

    host: str
    port: int
    dbname: str
    user: str
    password: str

    def __repr__(self) -> str:
        return f"DbSettings(host={self.host!r}, port={self.port}, dbname={self.dbname!r}, user={self.user!r})"

    @property
    def display(self) -> str:
        return f"{self.user}@{self.host}:{self.port}/{self.dbname}"


def load_settings(env_file: Path | None = None) -> DbSettings:
    """Read DB settings from the environment (after loading ``.env``); exit with a clear message if incomplete."""
    load_dotenv(env_file or PROJECT_ROOT / ".env")
    missing = [name for name in REQUIRED_VARS if not os.getenv(name)]
    if missing:
        raise SystemExit(
            f"Missing required environment variable(s): {', '.join(missing)}.\n"
            "Copy .env.example to .env and fill in the values (see sql/README.md)."
        )
    try:
        port = int(os.environ["POSTGRES_PORT"])
    except ValueError:
        raise SystemExit("POSTGRES_PORT must be an integer.") from None
    return DbSettings(os.environ["POSTGRES_HOST"], port, os.environ["POSTGRES_DB"],
                      os.environ["POSTGRES_USER"], os.environ["POSTGRES_PASSWORD"])


def connect(settings: DbSettings | None = None, *, autocommit: bool = False) -> psycopg.Connection:
    """Open a connection whose search_path points at the project schema."""
    s = settings or load_settings()
    try:
        return psycopg.connect(
            host=s.host, port=s.port, dbname=s.dbname, user=s.user, password=s.password,
            options=f"-c search_path={DB_SCHEMA},public", autocommit=autocommit, connect_timeout=10,
        )
    except psycopg.OperationalError as exc:
        raise SystemExit(
            f"Could not connect to {s.display}: {str(exc).strip()}\n"
            "Is the database running? Start it with: docker compose up -d"
        ) from exc
