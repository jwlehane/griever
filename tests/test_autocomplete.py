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


def test_dutchess_street_parts_does_not_abbreviate_south_street():
    predir, options = _clean_street_parts("South Street")

    assert predir == ""
    assert options == [
        "SOUTH STREET",
        "SOUTH",
    ]


def test_dutchess_street_parts_abbreviates_south_parsonage_street():
    predir, options = _clean_street_parts("South Parsonage Street")

    assert predir == "S"
    assert options == [
        "S PARSONAGE STREET",
        "S PARSONAGE",
        "PARSONAGE",
    ]


def test_dutchess_suggest_addresses_filters_by_swis_options():
    from app.counties.dutchess import DutchessCounty
    from unittest.mock import patch, MagicMock

    handler = DutchessCounty()
    
    with patch.object(handler.session, 'get') as mock_get:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "success": True,
            "data": [
                {
                    "parcelgrid": "135089123456",
                    "id": "135089123456",
                    "loc_st_nbr": "123",
                    "loc_st_name": "MAIN",
                    "loc_mail_st_suff": "ST",
                    "loc_muni_name": "RHINEBECK",
                    "loc_zip": "12572"
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        # Call suggest_addresses with a specific swis_options list (only Rhinebeck: 135089)
        results = handler.suggest_addresses("123 Main St", swis_options=["135089"])
        
        # Verify it only called session.get for SWIS code 135089
        assert len(results) == 1
        assert results[0]["town"] == "Rhinebeck"
        assert results[0]["parcelgrid"] == "135089123456"
        
        # Check that mock_get was called with 'swis': '135089'
        called_args, called_kwargs = mock_get.call_args
        assert called_kwargs['params']['swis'] == '135089'


def test_main_autocomplete_route_uses_census_preflight():
    import asyncio
    from main import autocomplete
    from unittest.mock import patch, MagicMock
    from fastapi import Request

    mock_request = MagicMock(spec=Request)
    mock_request.headers = {}
    
    census_mock = [
        {
            "label": "123 Main St, Poughkeepsie, NY 12601",
            "value": "123 Main St, Poughkeepsie, NY 12601",
            "address": "123 Main St",
            "town": "Poughkeepsie",
            "county": "Dutchess",
            "zip": "12601",
            "parcelgrid": "",
            "sbl": "",
            "source": "census"
        }
    ]

    with patch('main._census_autocomplete') as mock_census_ac, \
         patch('main._parcel_autocomplete') as mock_parcel_ac:
        
        mock_census_ac.return_value = (census_mock, "")
        mock_parcel_ac.return_value = []
        
        # Run async function using the active or new event loop without closing it
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        resp = loop.run_until_complete(autocomplete(mock_request, q="123 Main St"))
        
        mock_census_ac.assert_any_call("123 Main St", limit=5, timeout=2.0)
        
        called_args, called_kwargs = mock_parcel_ac.call_args
        assert "swis_options" in called_kwargs
        swis_opts = called_kwargs["swis_options"]
        assert "134689" in swis_opts or "131300" in swis_opts

