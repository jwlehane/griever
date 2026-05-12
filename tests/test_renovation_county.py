import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from app.core import TaxGrieveCore
from app.counties.factory import CountyFactory
from app.counties.dutchess import DutchessCounty

def test_effective_year_built():
    core = TaxGrieveCore()
    # Case 1: No renovation
    assert core.calculate_effective_year_built(1950, None) == 1950
    # Case 2: Major renovation
    # (1950 + 2010) / 2 = 1980
    assert core.calculate_effective_year_built(1950, 2010) == 1980
    # Case 3: Renovation before built (invalid but handled)
    assert core.calculate_effective_year_built(1950, 1940) == 1950

def test_county_factory():
    # Test default
    handler = CountyFactory.get_county_handler("123 Main St, Rhinebeck, NY")
    assert isinstance(handler, DutchessCounty)

def test_valuation_with_renovation():
    core = TaxGrieveCore()
    subject = {
        'address': 'Subject St',
        'year_built': 1950,
        'sqft': 2000,
        'acreage': 1.0,
        'bedrooms': 3,
        'bathrooms': 2.0,
        'assessment_2025': 500000
    }
    comps = [{
        'address': 'Comp St',
        'sale_price': 500000,
        'year_built': 1950,
        'sqft': 2000,
        'acreage': 1.0,
        'bedrooms': 3,
        'bathrooms': 2.0,
        'distance_miles': 0.1
    }]
    
    # Without renovation, reconciled should be 500,000
    valuation_none = core.calculate_valuation(subject, comps)
    val_none = valuation_none['market_value']
    results_none = valuation_none['comps']
    assert val_none == 500000
    
    # With renovation in 2010, effective year is 1980.
    # Subject (1980) vs Comp (1950) = 30 year difference.
    # Adjustment = (1980 - 1950) * 1000 = +30,000
    valuation_renov = core.calculate_valuation(subject, comps, renovation_year=2010)
    val_renov = valuation_renov['market_value']
    results_renov = valuation_renov['comps']
    assert results_renov[0]['reconciled_value'] == 530000
