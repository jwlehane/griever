import sys
import os
import pytest
import sqlite3
from unittest.mock import patch, MagicMock

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from app.core import TaxGrieveCore
from app.counties.dutchess import DutchessCounty

def setup_test_db(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE properties (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            address TEXT NOT NULL,
            sbl TEXT UNIQUE,
            sqft REAL,
            bedrooms INTEGER,
            bathrooms REAL,
            acreage REAL,
            assessed_value_2026 REAL,
            property_class TEXT,
            year_built INTEGER,
            assessment_2025 REAL
        )
    """)
    cursor.execute("""
        CREATE TABLE sales_comps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            address TEXT NOT NULL,
            sbl TEXT,
            sale_date TEXT,
            sale_price REAL,
            sqft REAL,
            bedrooms INTEGER,
            bathrooms REAL,
            acreage REAL,
            distance_miles REAL,
            reconciled_value REAL,
            year_built INTEGER,
            target_property_id INTEGER,
            source TEXT DEFAULT 'MANUAL',
            similarity_score REAL DEFAULT 0,
            is_outlier INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

def test_full_pipeline_flow():
    # Setup
    db_path = 'test_grievance.db'
    if os.path.exists(db_path): os.remove(db_path)
    setup_test_db(db_path)
    
    core = TaxGrieveCore(db_path=db_path)
    
    # 1. Subject Data
    subject_data = {
        'address': '67 N Parsonage St',
        'sbl': '13500100617000156384180000',
        'sqft': 2500,
        'acreage': 0.5,
        'bedrooms': 4,
        'bathrooms': 2.5,
        'year_built': 2005,
        'assessment_2025': 900000
    }
    
    # 2. Ensure Property
    prop_id = core.ensure_property(subject_data)
    assert prop_id is not None
    
    # 3. Add Manual Comp (Mocking the county handler verification)
    with patch('app.counties.factory.CountyFactory.get_county_handler') as mock_factory:
        mock_handler = MagicMock(spec=DutchessCounty)
        mock_factory.return_value = mock_handler
        
        mock_handler.search_address.return_value = {'parcelgrid': 'COMP1_SBL'}
        mock_handler.get_full_rps_data.return_value = {
            'address': '70 N Parsonage St',
            'sbl': 'COMP1_SBL',
            'sqft': 2400,
            'acreage': 0.5,
            'bedrooms': 4,
            'bathrooms': 2.5,
            'year_built': 2005,
            'assessment_2025': 850000
        }
        
        success = core.add_manual_comp(prop_id, '70 N Parsonage St', 850000)
        assert success is True

    # 4. Run Valuation
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sales_comps WHERE target_property_id = ?", (prop_id,))
    comps = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    market_value, results = core.calculate_valuation(subject_data, comps)
    
    assert market_value > 800000
    assert len(results) == 1
    assert results[0]['similarity_score'] > 90 # Should be very similar
    
    # Cleanup
    if os.path.exists(db_path): os.remove(db_path)
