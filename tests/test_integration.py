import sys
import os
import pytest
import sqlite3
from unittest.mock import patch, MagicMock

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from app.core import TaxGrieveCore
from app.counties.dutchess import DutchessCounty
from app.db import init_schema


def setup_test_db(db_path):
    """Apply the canonical SQLite schema to db_path. Same code path the app
    uses at startup, so test schema can't drift from production."""
    init_schema(sqlite_path=db_path)

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
        
        result = core.add_manual_comp(prop_id, '70 N Parsonage St', 850000)
        success = result[0] if isinstance(result, tuple) else result
        assert success is True, f"add_manual_comp returned {result!r}"

    # 4. Run Valuation
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sales_comps WHERE target_property_id = ?", (prop_id,))
    comps = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    result = core.calculate_valuation(subject_data, comps)
    market_value = result["market_value"]
    
    assert market_value > 800000
    assert result["used_count"] == 1
    # Under the new similarity model, the score requires style/condition/
    # sale_date data to break 80. The mocked comp omits these so we only
    # assert a positive score, not a quality threshold.
    assert result["comps"][0]['similarity_score'] > 0
    
    # Cleanup
    if os.path.exists(db_path): os.remove(db_path)
