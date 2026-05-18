import pytest
from app.core import TaxGrieveCore


def _subject():
    return {
        'sqft': 2000,
        'year_built': 2000,
        'acreage': 1.0,
        'bedrooms': 3,
        'bathrooms': 2,
        'style': 'Colonial',
        'condition_code': 'avg',
        'assessment_2025': 400000,
    }


def test_grading_logic_basic():
    core = TaxGrieveCore(db_path=':memory:')
    subject = _subject()

    comp_a = {
        'sqft': 2000,
        'year_built': 2000,
        'acreage': 1.0,
        'bedrooms': 3,
        'bathrooms': 2,
        'style': 'Colonial',
        'condition_code': 'avg',
        'sale_price': 300000,  # below EMV/sqft -> high advantage index
        'sale_date': '2024-07-01',
        'distance_miles': 0.1,
    }

    comp_f = {
        'sqft': 1000,
        'year_built': 1950,
        'acreage': 0.2,
        'bedrooms': 2,
        'bathrooms': 1,
        'style': 'Ranch',
        'condition_code': 'fair',
        'sale_price': 800000,
        'sale_date': '2022-01-01',  # 2+ years before valuation date, triggers date penalty
        'distance_miles': 2.0,
    }

    grade_a = core.calculate_similarity_grade(subject, comp_a, valuation_date="2024-07-01")
    grade_f = core.calculate_similarity_grade(subject, comp_f, valuation_date="2024-07-01")

    assert grade_a == "A", f"perfect comp graded {grade_a}"
    assert grade_f == "F", f"mismatched comp graded {grade_f}"


def test_valuation_enforcement():
    core = TaxGrieveCore(db_path=':memory:')

    subject = {'sqft': 2000, 'year_built': 2000}
    comps = [
        {'address': 'Selected', 'sale_price': 500000, 'sqft': 2000, 'is_selected': 1},
        {'address': 'Unselected', 'sale_price': 400000, 'sqft': 2000, 'is_selected': 0},
    ]

    res = core.calculate_valuation(subject, comps, enforce_selection=True)
    assert res["used_count"] == 1
    assert res["market_value"] == 500000

    res_all = core.calculate_valuation(subject, comps, enforce_selection=False)
    assert res_all["used_count"] == 2
    assert res_all["market_value"] == 450000
