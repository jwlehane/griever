import sys
import os
import pytest

# Add src to path so we can import app.core
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from app.core import TaxGrieveCore

def test_valuation_math_basic():
    """Verify that valuation math returns consistent results when no adjustments are needed."""
    core = TaxGrieveCore(db_path=':memory:') # Use in-memory DB for tests
    
    subject = {
        'sqft': 2000, 
        'acreage': 1.0, 
        'bathrooms': 2.0, 
        'bedrooms': 3, 
        'year_built': 2000,
        'address': '123 Subject St'
    }
    
    # Comp is identical to subject
    comps = [{
        'address': 'Comp 1',
        'sale_price': 500000,
        'sqft': 2000,
        'acreage': 1.0,
        'bathrooms': 2.0,
        'bedrooms': 3,
        'year_built': 2000
    }]

    result = core.calculate_valuation(subject, comps)
    market_value = result["market_value"]
    assert market_value == 500000
    assert result["used_count"] == 1
    assert result["comps"][0]['reconciled_value'] == 500000
    assert all(adj == 0 for adj in result["comps"][0]['adjustments'].values())

def test_valuation_adjustments():
    """Verify that adjustments are applied correctly."""
    core = TaxGrieveCore(db_path=':memory:')
    
    subject = {
        'sqft': 2500, # Subject is larger
        'acreage': 1.0, 
        'bathrooms': 2.0, 
        'bedrooms': 3, 
        'year_built': 2000
    }
    
    comps = [{
        'address': 'Comp 1', 
        'sale_price': 500000, 
        'sqft': 2000, # Comp is smaller
        'acreage': 1.0, 
        'bathrooms': 2.0, 
        'bedrooms': 3, 
        'year_built': 2000
    }]
    
    # $150 per sqft adjustment (default)
    # (2500 - 2000) * 150 = 500 * 150 = 75,000
    result = core.calculate_valuation(subject, comps)
    market_value = result["market_value"]
    assert market_value == 575000
    assert result["used_count"] == 1
    assert result["comps"][0]['adjustments']['gla'] == 75000
