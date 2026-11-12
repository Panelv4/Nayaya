"""Shared SQLite plumbing for the NYAYA-RAC portal (paths configurable via env
so the test-suite can run against throwaway databases)."""

from __future__ import annotations

import datetime as dt
import os
import sqlite3
from threading import RLock

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("NYAYA_DB", os.path.join(ROOT, "nyaya-rac.sqlite3"))
EVIDENCE_DIR = os.environ.get("NYAYA_EVIDENCE_DIR", os.path.join(ROOT, "evidence"))

# NOTE: both guards are REENTRANT. server.py holds LOCK while calling into
# legal_kb (which takes LOCK again for provenance edges); a plain Lock would
# self-deadlock. The server is threaded, so the lock is still doing real work.
LOCK = RLock()        # guards portal + KB writes
ENGINE_LOCK = RLock() # guards engine evaluate / rule-base reloads


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def now_dt() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def today() -> dt.date:
    return dt.date.today()


class _ClosingConnection(sqlite3.Connection):
    """`with db() as c:` commits (or rolls back) AND closes the handle.

    The stdlib connection context manager only manages the transaction; leaving
    handles open leaked file descriptors and kept write locks alive long enough
    for other connections to time out with "database is locked"."""

    def __exit__(self, exc_type, exc, tb):
        try:
            return super().__exit__(exc_type, exc, tb)
        finally:
            self.close()


def db() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=30, factory=_ClosingConnection)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


def ensure_columns(c: sqlite3.Connection, table: str, cols: list[tuple[str, str]]) -> None:
    """Lightweight migration: add missing columns to an existing table."""
    have = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
    for name, ddl in cols:
        if name not in have:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
