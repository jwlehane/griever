import sys
import os
import pytest
from unittest.mock import MagicMock, patch

# Add src to path so we can import app.core
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from app.core import MarketDataSourceError, TaxGrieveCore

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

def test_subject_profile_by_identifier_skips_fuzzy_search():
    core = TaxGrieveCore(db_path=':memory:')
    county = MagicMock()
    county.search_address = MagicMock()
    county.get_town_from_identifier.return_value = 'Kingston'
    county.get_full_rps_data.return_value = {
        'address': '60 Orchard St',
        'sbl': '51080005603400090260000000',
        'sqft': 1800,
        'acreage': 0.1,
        'bedrooms': 3,
        'bathrooms': 2.0,
        'year_built': 1920,
        'assessment_2026': 400000,
        'assessment_2025': 0,
        'property_class': '210',
    }

    with patch('app.core.CountyFactory.get_county_handler', return_value=county) as factory:
        with patch.object(core, '_fetch_rapidapi_comps', return_value=[]):
            with patch.object(core, '_geocode', return_value=(41.93, -74.01, '12401')):
                profile = core.get_subject_profile_by_identifier(
                    '51080005603400090260000000',
                    address_string='60 Orchard St, Kingston, NY 12401',
                    zip_code='12401',
                )

    factory.assert_called_once_with(
        address_string='60 Orchard St, Kingston, NY 12401',
        zip_code='12401',
        sbl='51080005603400090260000000',
    )
    county.search_address.assert_not_called()
    county.get_full_rps_data.assert_called_once_with('51080005603400090260000000')
    assert profile['sbl'] == '51080005603400090260000000'
    assert profile['zip'] == '12401'
    assert profile['latitude'] == 41.93

def test_finish_subject_profile_uses_market_tax_value_as_current_assessment():
    core = TaxGrieveCore(db_path=':memory:')
    county = MagicMock()
    county.get_town_from_identifier.return_value = 'Kingston'
    profile = {
        'address': '60 Orchard St',
        'sbl': '51080005603400090260000000',
        'sqft': 0,
        'acreage': 0,
        'bedrooms': 0,
        'bathrooms': 0,
        'year_built': 0,
        'assessment_2025': 0,
        'assessment_2026': 0,
    }
    market = [{
        'livingArea': 2413,
        'bedrooms': 3,
        'bathrooms': 2,
        'yearBuilt': 1973,
        'taxAssessedValue': 448936,
    }]

    with patch.object(core, '_fetch_rapidapi_comps', return_value=market):
        with patch.object(core, '_geocode', return_value=(41.93, -74.01, '12401')):
            result = core._finish_subject_profile(
                profile,
                '51080005603400090260000000',
                county,
                address_string='60 Orchard St, Kingston, NY 12401',
                zip_code='12401',
            )

    assert result['sqft'] == 2413
    assert result['assessment_2025'] == 448936
    assert result['assessment_2026'] == 448936


def test_rapidapi_quota_raises_clear_error(monkeypatch):
    core = TaxGrieveCore(db_path=':memory:')
    monkeypatch.setenv('RAPIDAPI_KEY', 'test-key')

    class Response:
        status_code = 429

        def raise_for_status(self):
            raise AssertionError("raise_for_status should not be reached for quota errors")

    with patch('requests.get', return_value=Response()):
        with pytest.raises(MarketDataSourceError) as exc:
            core._fetch_rapidapi_comps('Kingston, NY', 1, 99, 'RECENTLY_SOLD')

    assert "monthly quota is exhausted" in str(exc.value)

def test_comp_verification_address_includes_city_and_zip():
    core = TaxGrieveCore(db_path=':memory:')

    result = core._comp_verification_address(
        {'addressCity': 'Kingston', 'addressState': 'NY', 'zipcode': '12401'},
        '168-170 Lucas Avenue Avenue',
    )

    assert result == '168-170 Lucas Avenue Avenue, Kingston, NY 12401'


@pytest.mark.parametrize(
    ("input_address", "official_address"),
    [
        ("1562 Centre Road", "1562 Centre Rd"),
        ("168-170 Lucas Avenue Avenue", "168-170 Lucas Ave"),
        ("94 Hill Top Rd", "94 Hilltop Rd"),
    ],
)
def test_address_verification_accepts_same_parcel_address(input_address, official_address):
    core = TaxGrieveCore(db_path=':memory:')

    assert core._addresses_match_for_verification(input_address, official_address)


@pytest.mark.parametrize(
    ("input_address", "official_address"),
    [
        ("9 Mountain View Court", "99 Mountain View Rd"),
        ("25 Mountain View Court", "25 Mountain View Rd"),
        ("5 Orchard St", "51 Orchard Pl"),
        ("5 Orchard St", "5 Orchard Pl"),
    ],
)
def test_address_verification_rejects_wrong_parcel_address(input_address, official_address):
    core = TaxGrieveCore(db_path=':memory:')

    assert not core._addresses_match_for_verification(input_address, official_address)
