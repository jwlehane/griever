"""Database abstraction layer.

Dual-driver: SQLite for local dev (no DATABASE_URL), Postgres for prod (set
DATABASE_URL to a postgres:// or postgresql:// URL).

Cursor returns are normalized so callers can use the SQLite idioms they were
already writing: ?-placeholders, tuple/Row results, `cursor.lastrowid` after
INSERT. The PostgresCursor translates these to %s, dict rows, and a RETURNING
id round-trip respectively.

Portable SQL helpers (UPSERT, table-exists) live here too so call sites don't
have to fork on driver type — they were doing `INSERT OR REPLACE` everywhere,
which is SQLite-only and was silently broken on Postgres.
"""

import os
import sqlite3
import re
from pathlib import Path

DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    import psycopg2
    import psycopg2.extras


_SCHEMA_DIR = Path(__file__).parent


def get_connection(sqlite_path: str = 'grievance_data.db'):
    """Return a connection. Postgres if DATABASE_URL is set (sqlite_path is
    ignored in that case), otherwise SQLite at `sqlite_path`."""
    if DATABASE_URL:
        return PostgresConnection(psycopg2.connect(DATABASE_URL))
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    return SQLiteConnection(conn)


def init_schema(sqlite_path: str = 'grievance_data.db'):
    """Apply the canonical schema for the active driver. Idempotent.

    Call once at startup. Both schema files use CREATE TABLE IF NOT EXISTS,
    so this is safe to run on every boot.
    """
    schema_file = "schema_postgres.sql" if DATABASE_URL else "schema_sqlite.sql"
    sql = (_SCHEMA_DIR / schema_file).read_text()

    if DATABASE_URL:
        conn = psycopg2.connect(DATABASE_URL)
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()
        finally:
            conn.close()
    else:
        conn = sqlite3.connect(sqlite_path)
        try:
            conn.executescript(sql)
            conn.commit()
        finally:
            conn.close()


def is_postgres() -> bool:
    """Lets call sites pick driver-specific syntax (UPSERT, table-exists)
    without re-reading the env var."""
    return bool(DATABASE_URL)


def upsert_sql(table: str, columns: list[str], conflict_cols: list[str]) -> str:
    """Build a portable UPSERT statement.

    SQLite: INSERT OR REPLACE (replaces the whole row; we always pass every
        column so this is equivalent to upsert).
    Postgres: INSERT ... ON CONFLICT (...) DO UPDATE SET col=EXCLUDED.col ...

    Returns a SQL string with ?-placeholders. Callers using the abstraction's
    cursor will get them translated automatically for Postgres.
    """
    placeholders = ",".join(["?"] * len(columns))
    col_list = ",".join(columns)
    if is_postgres():
        conflict_list = ",".join(conflict_cols)
        update_set = ",".join(
            f"{c}=EXCLUDED.{c}" for c in columns if c not in conflict_cols
        )
        return (
            f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
            f"ON CONFLICT ({conflict_list}) DO UPDATE SET {update_set}"
        )
    return f"INSERT OR REPLACE INTO {table} ({col_list}) VALUES ({placeholders})"


def column_exists(cursor, table: str, column: str) -> bool:
    """Driver-agnostic 'does this column exist?' check.

    Used by the legacy runtime-migration block in core.py that we keep around
    as a belt-and-suspenders for old SQLite DBs predating init_schema.
    """
    if is_postgres():
        cursor.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name=? AND column_name=?",
            (table, column),
        )
        return cursor.fetchone() is not None
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())


class SQLiteConnection:
    def __init__(self, conn):
        self.conn = conn

    def cursor(self):
        return self.conn.cursor()

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()

    def execute(self, query, params=None):
        return self.conn.execute(query, params or ())


class PostgresConnection:
    def __init__(self, conn):
        self.conn = conn

    def cursor(self):
        return PostgresCursor(
            self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        )

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()

    def execute(self, query, params=None):
        c = self.cursor()
        c.execute(query, params)
        return c


class PostgresCursor:
    def __init__(self, cursor):
        self.cursor = cursor
        self._lastrowid = None

    @staticmethod
    def _translate_query(query: str) -> str:
        # Convert ?-placeholders to %s. We assume no '?' inside string
        # literals in our specific queries (audited; none).
        return query.replace('?', '%s')

    def execute(self, query, params=None):
        q = self._translate_query(query)
        is_insert = q.strip().upper().startswith("INSERT")
        # If the caller didn't provide RETURNING, append one so we can fill
        # lastrowid the way SQLite does.
        if is_insert and "RETURNING" not in q.upper():
            q = q + " RETURNING id"

        self.cursor.execute(q, params or ())

        if is_insert:
            try:
                row = self.cursor.fetchone()
                if row and 'id' in row:
                    self._lastrowid = row['id']
            except psycopg2.ProgrammingError:
                # Some INSERT...ON CONFLICT DO UPDATE statements with no RETURNING
                # leave nothing to fetch. Tolerate it.
                self._lastrowid = None
        return self

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()

    @property
    def lastrowid(self):
        return self._lastrowid
