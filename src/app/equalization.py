"""Equalization rate (ER) / Residential Assessment Ratio (RAR) lookup.

Source data:
- Dutchess: County RPTS 2024/2025 tax-rate publication (ER per municipality).
- Ulster: NYS ORPTS / O'Donnell & Cullen 2025 RAR per municipality.

Use RAR for residential grievance math; ER and RAR are typically the same in
towns at 100% but diverge in fractional-assessment municipalities. The values
below are the residential-applicable ratios as percentages (0-100).
"""

from __future__ import annotations
from typing import Optional


# SWIS prefix → rate (percent, 0-100). Keyed by 6-digit SWIS so the lookup
# works directly off a property's SBL.
ER_BY_SWIS: dict[str, float] = {
    # ---------- DUTCHESS (county code 13) ----------
    "132000": 100.00,  # Amenia
    "130200": 100.00,  # Beacon (city)
    "132200": 66.85,   # Beekman
    "132400": 100.00,  # Clinton
    "132600": 34.50,   # Dover
    "132800": 100.00,  # East Fishkill
    "133089": 100.00,  # Fishkill (town outside village)
    "133001": 100.00,  # Fishkill (village)
    "133200": 37.00,   # Hyde Park
    "133400": 71.00,   # LaGrange
    "133600": 100.00,  # Milan
    "135801": 78.00,   # Millbrook (village; town reports under Washington)
    "133801": 100.00,  # Millerton (village)
    "133889": 100.00,  # Northeast
    "134089": 31.36,   # Pawling (town outside village)
    "134001": 32.78,   # Pawling (village)
    "134200": 100.00,  # Pine Plains
    "134400": 73.25,   # Pleasant Valley
    "134689": 94.00,   # Poughkeepsie (town)
    "131300": 100.00,  # Poughkeepsie (city)
    "134889": 100.00,  # Red Hook (town)
    "134801": 100.00,  # Red Hook (village)
    "135089": 100.00,  # Rhinebeck (town)
    "135001": 100.00,  # Rhinebeck (village)
    "135200": 100.00,  # Stanford
    "134803": 100.00,  # Tivoli (village)
    "135400": 71.00,   # Union Vale
    "135689": 100.00,  # Wappinger (town)
    "135889": 74.36,   # Washington

    # ---------- ULSTER (county code 51) ----------
    "510800": 44.03,   # Kingston (city)
    "512000": 7.87,    # Denning
    "512200": 51.00,   # Esopus
    "512400": 57.50,   # Gardiner
    "512600": 29.56,   # Hardenburgh
    "512800": 91.30,   # Hurley
    "513000": 37.36,   # Kingston (town)
    "513200": 59.26,   # Lloyd
    "513400": 52.00,   # Marbletown
    "513600": 56.56,   # Marlborough
    "513801": 58.00,   # New Paltz (town)
    "513889": 58.00,   # New Paltz (village)
    "514000": 100.00,  # Olive
    "514200": 55.00,   # Plattekill
    "514400": 53.00,   # Rochester
    "514600": 56.00,   # Rosendale
    "514801": 100.00,  # Saugerties (town)
    "514889": 100.00,  # Saugerties (village)
    "515000": 10.23,   # Shandaken
    "515200": 11.20,   # Shawangunk
    "515400": 36.45,   # Ulster (town)
    "515601": 49.32,   # Wawarsing (town)
    "515689": 49.32,   # Wawarsing (village)
    "515800": 47.00,   # Woodstock
}

YEAR = 2025  # data vintage for both counties


def get_rate(sbl_or_swis: Optional[str]) -> Optional[float]:
    """Return the equalization rate (percent, 0-100) for the SWIS embedded
    in the SBL/SWIS string. None when unknown."""
    if not sbl_or_swis:
        return None
    swis = sbl_or_swis[:6]
    return ER_BY_SWIS.get(swis)


def implied_market_value(assessed_value: float, sbl_or_swis: Optional[str]) -> Optional[float]:
    """Convert an assessed value to its full-market-value equivalent using
    the municipality's equalization rate. Returns None when the rate is
    unknown so callers can fall back gracefully.

    `assessed_value` should be the value from the current tax roll (TOTAL_AV).
    """
    rate = get_rate(sbl_or_swis)
    if not rate or not assessed_value or rate <= 0:
        return None
    return assessed_value / (rate / 100.0)
