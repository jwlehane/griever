import pytest
from app.core import TaxGrieveCore
import datetime

def test_grading_logic_basic():
    core = TaxGrieveCore(db_path=':memory:')
    
    subject = {
        'sqft': 2000,
        'year_built': 2000,
        'acreage': 1.0,
        'bedrooms': 3,
        'bathrooms': 2
    }
    
    # Perfect match, recent sale
    comp_a = {
        'sqft': 2000,
        'year_built': 2000,
        'acreage': 1.0,
        'bedrooms': 3,
        'bathrooms': 2,
        'sale_date': '2024-06-01', # Just before valuation date
        'distance_miles': 0.1
    }
    
    # Mismatch in size, old sale
    comp_f = {
        'sqft': 1000,
        'year_built': 1950,
        'acreage': 0.2,
        'bedrooms': 2,
        'bathrooms': 1,
        'sale_date': '2022-01-01', # 2 years before valuation date
        'distance_miles': 2.0
    }
    
    grade_a = core.calculate_similarity_grade(subject, comp_a, valuation_date="2024-07-01")
    grade_f = core.calculate_similarity_grade(subject, comp_f, valuation_date="2024-07-01")
    
    assert grade_a == "A"
    assert grade_f == "F"

def test_valuation_enforcement():
    core = TaxGrieveCore(db_path=':memory:')
    
    subject = {'sqft': 2000, 'year_built': 2000}
    comps = [
        {'address': 'Selected', 'sale_price': 500000, 'sqft': 2000, 'is_selected': 1},
        {'address': 'Unselected', 'sale_price': 400000, 'sqft': 2000, 'is_selected': 0}
    ]
    
    # Enforce selection
    res = core.calculate_valuation(subject, comps, enforce_selection=True)
    assert res["used_count"] == 1
    assert res["market_value"] == 500000
    
    # Don't enforce
    res_all = core.calculate_valuation(subject, comps, enforce_selection=False)
    assert res_all["used_count"] == 2
    # Median of 500k and 400k
    assert res_all["market_value"] == 450000
