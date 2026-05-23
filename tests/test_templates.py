import os
import sys

from jinja2 import Environment, FileSystemLoader, select_autoescape

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))


def _env():
    return Environment(
        loader=FileSystemLoader(os.path.join(os.path.dirname(__file__), '..', 'src', 'templates')),
        autoescape=select_autoescape(['html']),
    )


def _subject():
    return {
        'address': '33 Cedar Heights Rd',
        'bedrooms': 4,
        'bathrooms': 1.5,
        'sqft': 1776,
        'year_built': 1947,
    }


def _comp(idx, selected=False):
    return {
        'address': f'{idx} Test Comp Rd',
        'distance_miles': 1.2,
        'sale_price': 500000 + idx,
        'sale_date': '2026-03-20',
        'sqft': 1700,
        'bedrooms': 4,
        'bathrooms': 2,
        'year_built': 1950,
        'reconciled_value': 480000 + idx,
        'adjustments': {'gla': 0, 'acreage': 0, 'bath': 0, 'bed': 0, 'age': 0},
        'zpid': f'z-{idx}',
        'is_selected': 1 if selected else 0,
        'is_outlier': False,
        'similarity_score': 50 + idx,
        'grade': 'C',
        'status': 'VERIFIED',
    }


def test_index_template_exposes_progress_and_safe_resume_hooks():
    html = _env().get_template('index.html').render()

    assert 'id="address-status"' in html
    assert 'id="verified-count"' in html
    assert 'id="checked-count"' in html
    assert "setOptionalDisplay('resume-btn'" in html


def test_curation_template_blocks_finalize_until_three_selected():
    html = _env().get_template('curation.html').render(
        subject=_subject(),
        subject_id=1,
        comps=[_comp(1, selected=True), _comp(2, selected=True), _comp(3)],
        renovation_year=None,
        condition='average',
    )

    assert 'id="selection-banner"' in html
    assert 'id="selected-count">2</b>' in html
    assert 'id="finalize-btn" type="submit" class="btn-finalize" disabled' in html
    assert 'data-label="Match"' in html
    assert 'function updateSelectionSummary()' in html
    assert "onclick='toggleSelect(" in html
    assert 'onclick="toggleSelect(' not in html


def test_curation_template_allows_finalize_after_three_selected():
    html = _env().get_template('curation.html').render(
        subject=_subject(),
        subject_id=1,
        comps=[_comp(1, selected=True), _comp(2, selected=True), _comp(3, selected=True)],
        renovation_year=None,
        condition='average',
    )

    assert 'selection-banner ready' in html
    assert 'id="selected-count">3</b>' in html
    finalize_button = html.split('id="finalize-btn"', 1)[1].split('>', 1)[0]
    assert 'disabled' not in finalize_button
