import os
import sys
from datetime import date

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from app.core import TaxGrieveCore


def test_evidence_quality_high_for_verified_complete_recent_comps():
    core = TaxGrieveCore(db_path=':memory:')
    subject = {
        'address': '123 Subject St',
        'sbl': '13500100000000000000000000',
        'sqft': 2000,
        'acreage': 1.0,
        'bedrooms': 3,
        'bathrooms': 2.0,
        'year_built': 1990,
        'assessment_2026': 450000,
    }
    comps = [
        {
            'address': f'Comp {i}',
            'status': 'VERIFIED',
            'used': True,
            'is_outlier': False,
            'sale_price': 450000 + (i * 10000),
            'sale_date': '2026-01-15',
            'sqft': 1980 + i,
            'acreage': 1.0,
            'bedrooms': 3,
            'bathrooms': 2.0,
            'year_built': 1990 + i,
        }
        for i in range(3)
    ]

    quality = core.calculate_evidence_quality(subject, comps, today=date(2026, 5, 12))

    assert quality['score'] >= 90
    assert quality['label'] == 'High'
    assert quality['warnings'] == []
    assert quality['components'][0]['key'] == 'verified_comps'


def test_evidence_quality_flags_unverified_missing_stale_and_outlier_inputs():
    core = TaxGrieveCore(db_path=':memory:')
    subject = {
        'address': '123 Subject St',
        'sbl': '13500100000000000000000000',
        'sqft': 2000,
        'acreage': 1.0,
        'bedrooms': 3,
        'bathrooms': 2.0,
        'year_built': 1990,
        'assessment_2026': 450000,
    }
    comps = [
        {
            'address': 'Weak Comp',
            'status': 'UNVERIFIED',
            'used': True,
            'is_outlier': True,
            'sale_price': 450000,
            'sale_date': '2021-01-15',
            'sqft': 1980,
            'acreage': 1.0,
            'bedrooms': 3,
            'bathrooms': 2.0,
            'year_built': 0,
        }
    ]

    quality = core.calculate_evidence_quality(subject, comps, today=date(2026, 5, 12))

    assert quality['score'] < 60
    assert quality['class'] in {'low', 'weak'}
    assert any('Fewer than three' in warning for warning in quality['warnings'])
    assert any('not county-verified' in warning for warning in quality['warnings'])
    assert any('missing year-built' in warning for warning in quality['warnings'])
    assert any('more than 24 months old' in warning for warning in quality['warnings'])
    assert any('flagged as outliers' in warning for warning in quality['warnings'])
