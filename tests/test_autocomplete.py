import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from app.counties.dutchess import _clean_street_parts
from app.counties.ulster import _street_options


def test_ulster_street_options_match_long_and_short_suffixes():
    assert _street_options("Orchard Street") == [
        "ORCHARD STREET",
        "ORCHARD ST",
        "ORCHARD",
    ]


def test_dutchess_street_parts_normalize_direction_and_suffix():
    predir, options = _clean_street_parts("North Parsonage Street")

    assert predir == "N"
    assert options == [
        "N PARSONAGE STREET",
        "N PARSONAGE",
        "PARSONAGE",
    ]
