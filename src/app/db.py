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

# Always import psycopg2 if installed; we gate actual use on DATABASE_URL at
# call time (not import time) so Cloud Run secret injection is never missed.
try:
    import psycopg2
    import psycopg2.extras
    _PSYCOPG2_AVAILABLE = True
except ImportError:
    _PSYCOPG2_AVAILABLE = False


def _database_url() -> str | None:
    """Read DATABASE_URL fresh from the environment each time.

    Do NOT cache at module level: Cloud Run injects secrets before the process
    starts, but keeping a module-level snapshot means any code that imports
    db.py during a test (or before the real app init) could freeze the value
    as None even though the env var is present for the actual server process.
    """
    return os.getenv("DATABASE_URL")


_SCHEMA_DIR = Path(__file__).parent


def get_connection(sqlite_path: str = 'grievance_data.db'):
    """Return a connection. Postgres if DATABASE_URL is set (sqlite_path is
    ignored in that case), otherwise SQLite at `sqlite_path`."""
    db_url = _database_url()
    if db_url:
        return PostgresConnection(psycopg2.connect(db_url))
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    return SQLiteConnection(conn)


def init_schema(sqlite_path: str = 'grievance_data.db'):
    """Apply the canonical schema for the active driver. Idempotent.

    Call once at startup. Both schema files use CREATE TABLE IF NOT EXISTS,
    so this is safe to run on every boot.
    """
    db_url = _database_url()
    schema_file = "schema_postgres.sql" if db_url else "schema_sqlite.sql"
    sql = (_SCHEMA_DIR / schema_file).read_text()

    if db_url:
        conn = psycopg2.connect(db_url)
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
    return bool(_database_url())


def upsert_sql(table: str, columns: list[str], conflict_cols: list[str],
               conflict_where: str | None = None) -> str:
    """Build a portable UPSERT statement.

    SQLite: INSERT OR REPLACE (replaces the whole row; we always pass every
        column so this is equivalent to upsert).
    Postgres: INSERT ... ON CONFLICT (...) [WHERE ...] DO UPDATE SET col=EXCLUDED.col ...

    conflict_where: optional predicate that must match the partial unique index
        definition (e.g. 'zpid IS NOT NULL' for the sales_comps index).
        Postgres ON CONFLICT must exactly match the index, including its WHERE.

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
        where_clause = f" WHERE {conflict_where}" if conflict_where else ""
        return (
            f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
            f"ON CONFLICT ({conflict_list}){where_clause} DO UPDATE SET {update_set}"
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
