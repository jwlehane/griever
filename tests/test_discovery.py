import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from app.core import TaxGrieveCore


def _full_subject():
    return {
        'sqft': 2000,
        'year_built': 2000,
        'acreage': 1.0,
        'bedrooms': 3,
        'bathrooms': 2,
        'style': 'Colonial',
        'condition_code': 'avg',
        'assessment_2025': 400000,
        'distance_miles': 0,
    }


def _full_comp(**overrides):
    base = {
        'sqft': 2000,
        'year_built': 2000,
        'acreage': 1.0,
        'bedrooms': 3,
        'bathrooms': 2,
        'style': 'Colonial',
        'condition_code': 'avg',
        'sale_price': 400000,
        'sale_date': '2024-06-15',
        'distance_miles': 0,
    }
    base.update(overrides)
    return base


def test_roll_year_drives_valuation_date():
    core = TaxGrieveCore(db_path=':memory:')
    assert core.get_roll_year({'assessment_2025': 400000}) == 2025
    assert core.get_roll_year({'assessment_2025': 400000, 'assessment_2026': 425000}) == 2026
    assert core.get_valuation_date({'assessment_2026': 425000}).isoformat() == '2025-07-01'
    assert core.get_current_assessment({'assessment_2025': 400000, 'assessment_2026': 425000}) == 425000


def test_hard_filter_uses_current_roll_valuation_date():
    core = TaxGrieveCore(db_path=':memory:')
    subject = {
        'sbl': '13508900000000000000000000',
        'sqft': 2000,
        'assessment_2026': 425000,
    }

    assert core._passes_hard_filters(subject, _full_comp(sale_date='2025-07-01', sbl='UNVERIFIED')) == (True, '')
    assert core._passes_hard_filters(subject, _full_comp(sale_date='2026-01-05', sbl='UNVERIFIED')) == (True, '')
    assert core._passes_hard_filters(subject, _full_comp(sale_date='2024-06-30', sbl='UNVERIFIED')) == (
        False,
        'Sale date outside 12-month window',
    )


def test_similarity_uses_current_roll_valuation_date():
    core = TaxGrieveCore(db_path=':memory:')
    subject = _full_subject()
    subject['assessment_2026'] = 425000

    on_date = core.calculate_similarity(subject, _full_comp(sale_date='2025-07-01'))
    old_date = core.calculate_similarity(subject, _full_comp(sale_date='2024-07-01'))

    assert on_date > old_date


def test_similarity_perfect_match_scores_high():
    """A comp identical to the subject, sold on the valuation date, with a
    favorable price/sqft, should score in the A range (>= 85). Note: the
    advantage index defaults to 50/100 when assessment data is absent, so
    we supply assessment_2025 + a sale_price below target EMV/sqft."""
    core = TaxGrieveCore(db_path=':memory:')
    # Subject EMV/sqft = 400000/2000 = $200. Comp price/sqft = 300000/2000 = $150,
    # ratio 0.75 -> advantage = 100 - (0.25*100) = 75.
    score = core.calculate_similarity(
        _full_subject(),
        _full_comp(sale_date='2024-07-01', sale_price=300000),
    )
    assert score >= 85, f"perfect match scored only {score}"


def test_similarity_gla_penalty_drops_score():
    """A 25% larger comp should lose all GLA points (max var is 20% in
    calculate_similarity), pulling the total score down by at least 10."""
    core = TaxGrieveCore(db_path=':memory:')
    baseline = core.calculate_similarity(_full_subject(), _full_comp())
    gla_off = core.calculate_similarity(_full_subject(), _full_comp(sqft=2500))
    assert gla_off < baseline - 10, f"expected GLA penalty (got {baseline} -> {gla_off})"


def test_similarity_age_mismatch_drops_style_points():
    """An identical comp 50 years older loses the era-match bonus (10 pts in
    the style component) but keeps everything else, so the score should still
    drop but only by single digits."""
    core = TaxGrieveCore(db_path=':memory:')
    baseline = core.calculate_similarity(_full_subject(), _full_comp())
    old = core.calculate_similarity(_full_subject(), _full_comp(year_built=1950))
    assert baseline > old > baseline - 15


def test_outlier_detection():
    """The IQR filter should still flag a 4x-priced comp as an outlier and
    exclude it from the median."""
    core = TaxGrieveCore(db_path=':memory:')
    subject = {'sqft': 2000, 'year_built': 2000, 'acreage': 1.0, 'bathrooms': 2, 'bedrooms': 3}
    comps = [
        {'address': 'Good 1', 'sale_price': 500000, 'sqft': 2000, 'year_built': 2000, 'acreage': 1.0, 'bathrooms': 2, 'bedrooms': 3},
        {'address': 'Good 2', 'sale_price': 510000, 'sqft': 2000, 'year_built': 2000, 'acreage': 1.0, 'bathrooms': 2, 'bedrooms': 3},
        {'address': 'Good 3', 'sale_price': 490000, 'sqft': 2000, 'year_built': 2000, 'acreage': 1.0, 'bathrooms': 2, 'bedrooms': 3},
        {'address': 'Outlier', 'sale_price': 2000000, 'sqft': 2000, 'year_built': 2000, 'acreage': 1.0, 'bathrooms': 2, 'bedrooms': 3},
    ]

    result = core.calculate_valuation(subject, comps)
    market_value = result["market_value"]

    outlier_result = next(r for r in result["comps"] if r['address'] == 'Outlier')
    assert outlier_result['is_outlier'] is True
    assert market_value == 500000
