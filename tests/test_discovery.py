import sys
import os
import pytest

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from app.core import TaxGrieveCore

def test_similarity_identical():
    core = TaxGrieveCore(db_path=':memory:')
    subject = {'sqft': 2000, 'year_built': 2000, 'acreage': 1.0, 'distance_miles': 0}
    comp = {'sqft': 2000, 'year_built': 2000, 'acreage': 1.0, 'distance_miles': 0}
    score = core.calculate_similarity(subject, comp)
    assert score == 100.0

def test_similarity_different_sqft():
    core = TaxGrieveCore(db_path=':memory:')
    subject = {'sqft': 2000, 'year_built': 2000, 'acreage': 1.0, 'distance_miles': 0}
    # 10% smaller sqft
    comp = {'sqft': 1800, 'year_built': 2000, 'acreage': 1.0, 'distance_miles': 0}
    score = core.calculate_similarity(subject, comp)
    # Sqft is 40% of total. 10% diff / 20% tolerance = 0.5. 
    # Sqft component = (1 - 0.5) * 40 = 20. Total = 20 + 30 + 20 + 10 = 80.
    assert score == 80.0

def test_similarity_different_age():
    core = TaxGrieveCore(db_path=':memory:')
    subject = {'sqft': 2000, 'year_built': 2000, 'acreage': 1.0, 'distance_miles': 0}
    # 25 years older
    comp = {'sqft': 2000, 'year_built': 1975, 'acreage': 1.0, 'distance_miles': 0}
    score = core.calculate_similarity(subject, comp)
    # Age is 30% of total. 25 year diff / 50 year tolerance = 0.5.
    # Age component = (1 - 0.5) * 30 = 15. Total = 40 + 15 + 20 + 10 = 85.
    assert score == 85.0

def test_outlier_detection():
    core = TaxGrieveCore(db_path=':memory:')
    subject = {'sqft': 2000, 'year_built': 2000, 'acreage': 1.0, 'bathrooms': 2, 'bedrooms': 3}
    # Need enough spread for Tukey fence to trigger or more extreme values
    comps = [
        {'address': 'Good 1', 'sale_price': 500000, 'sqft': 2000, 'year_built': 2000, 'acreage': 1.0, 'bathrooms': 2, 'bedrooms': 3},
        {'address': 'Good 2', 'sale_price': 510000, 'sqft': 2000, 'year_built': 2000, 'acreage': 1.0, 'bathrooms': 2, 'bedrooms': 3},
        {'address': 'Good 3', 'sale_price': 490000, 'sqft': 2000, 'year_built': 2000, 'acreage': 1.0, 'bathrooms': 2, 'bedrooms': 3},
        {'address': 'Outlier', 'sale_price': 2000000, 'sqft': 2000, 'year_built': 2000, 'acreage': 1.0, 'bathrooms': 2, 'bedrooms': 3}
    ]
    
    result = core.calculate_valuation(subject, comps)
    market_value = result["market_value"]
    
    # Outlier should be flagged
    outlier_result = next(r for r in result["comps"] if r['address'] == 'Outlier')
    assert outlier_result['is_outlier'] is True
    
    # Market value should be based on valid comps only (median of 490, 500, 510 is 500)
    assert market_value == 500000
