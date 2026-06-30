import sys
import os
from unittest.mock import patch, MagicMock
import pytest
import sqlite3

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

import app.db as db

@pytest.fixture(autouse=True)
def reset_fallback_state():
    db._use_sqlite_fallback = False
    db._fallback_notified = False
    yield
    db._use_sqlite_fallback = False
    db._fallback_notified = False

def test_fallback_activated_on_get_connection_failure():
    # Setup: mock database url and mock psycopg2.connect to fail
    with patch('app.db._database_url', return_value="postgresql://fake_user:fake_pass@localhost/fake_db"), \
         patch('app.db.psycopg2.connect', side_effect=Exception("Connection refused")), \
         patch('app.utils.send_error_report') as mock_send_report:
        
        assert db.is_postgres() is True
        
        # Act: call get_connection (uses test_fallback.db for sqlite fallback)
        test_sqlite_path = "test_fallback.db"
        if os.path.exists(test_sqlite_path):
            os.remove(test_sqlite_path)
            
        try:
            conn = db.get_connection(sqlite_path=test_sqlite_path)
            # Assertions
            assert db._use_sqlite_fallback is True
            assert db.is_postgres() is False
            assert isinstance(conn, db.SQLiteConnection)
            
            # Verify notification was sent
            mock_send_report.assert_called_once()
            
            # Call get_connection again, notification should not be sent again
            mock_send_report.reset_mock()
            conn2 = db.get_connection(sqlite_path=test_sqlite_path)
            assert isinstance(conn2, db.SQLiteConnection)
            mock_send_report.assert_not_called()
        finally:
            if os.path.exists(test_sqlite_path):
                os.remove(test_sqlite_path)

def test_fallback_activated_on_init_schema_failure():
    # Setup
    with patch('app.db._database_url', return_value="postgresql://fake_user:fake_pass@localhost/fake_db"), \
         patch('app.db.psycopg2.connect', side_effect=Exception("Connection refused")), \
         patch('app.utils.send_error_report') as mock_send_report:
        
        assert db.is_postgres() is True
        
        test_sqlite_path = "test_fallback_init.db"
        if os.path.exists(test_sqlite_path):
            os.remove(test_sqlite_path)
            
        try:
            db.init_schema(sqlite_path=test_sqlite_path)
            
            # Assertions
            assert db._use_sqlite_fallback is True
            assert db.is_postgres() is False
            
            mock_send_report.assert_called_once()
            
            # Verify SQLite schema was actually initialized
            conn = sqlite3.connect(test_sqlite_path)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='properties'")
            row = cursor.fetchone()
            assert row is not None
            conn.close()
        finally:
            if os.path.exists(test_sqlite_path):
                os.remove(test_sqlite_path)
