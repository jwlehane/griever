import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from app.counties.dutchess import _clean_street_parts
from app.counties.ulster import _parse_number_street, _street_options


def test_ulster_street_options_match_long_and_short_suffixes():
    assert _street_options("Orchard Street") == [
        "ORCHARD STREET",
        "ORCHARD ST",
        "ORCHARD",
    ]


def test_ulster_street_options_collapse_duplicate_suffixes():
    assert _street_options("Lucas Avenue Avenue") == [
        "LUCAS AVENUE",
        "LUCAS AVE",
        "LUCAS",
    ]


def test_ulster_address_parser_accepts_house_number_ranges():
    match = _parse_number_street("168-170 LUCAS AVE")

    assert match.group(1) == "168-170"
    assert match.group(2) == "LUCAS AVE"


def test_dutchess_street_parts_normalize_direction_and_suffix():
    predir, options = _clean_street_parts("North Parsonage Street")

    assert predir == "N"
    assert options == [
        "N PARSONAGE STREET",
        "N PARSONAGE",
        "PARSONAGE",
    ]


def test_dutchess_street_parts_try_compacted_multitoken_names():
    predir, options = _clean_street_parts("Hill Top Road")

    assert predir == ""
    assert options == [
        "HILL TOP ROAD",
        "HILL TOP",
        "HILLTOP",
    ]
