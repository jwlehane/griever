import os
import sqlite3
import re

DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    import psycopg2
    from psycopg2.extras import RealDictCursor

def get_connection():
    if DATABASE_URL:
        # Connect to Postgres
        conn = psycopg2.connect(DATABASE_URL)
        return PostgresConnection(conn)
    else:
        # Fallback to local SQLite
        conn = sqlite3.connect('grievance_data.db')
        conn.row_factory = sqlite3.Row
        return SQLiteConnection(conn)

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
        return PostgresCursor(self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor))
    
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
    
    def _translate_query(self, query):
        # Translate '?' to '%s'
        # Basic replacement. We assume no '?' inside string literals in our specific queries.
        return query.replace('?', '%s')
        
    def execute(self, query, params=None):
        q = self._translate_query(query)
        is_insert = q.strip().upper().startswith("INSERT")
        if is_insert and "RETURNING" not in q.upper():
            q = q + " RETURNING id"
            
        self.cursor.execute(q, params or ())
        
        if is_insert:
            row = self.cursor.fetchone()
            if row and 'id' in row:
                self._lastrowid = row['id']
                
        return self
        
    def fetchone(self):
        return self.cursor.fetchone()
        
    def fetchall(self):
        return self.cursor.fetchall()
        
    @property
    def lastrowid(self):
        return self._lastrowid
