"""Per-municipality adjustment factors used by the sales-comparison approach.

These are rough first-cut factors derived from local market knowledge; the
proper way to set them is paired-sales regression on the NYS ORPTS RP-5217
sales file. The dict is keyed by SWIS prefix so it works directly from a
property's SBL. Missing keys fall through to a sensible default.

Units:
- sqft: dollars per sqft of GLA difference
- bathroom: dollars per full bath equivalent (half-bath = 0.5)
- bedroom: dollars per bedroom
- acre: dollars per acre of lot-size difference
- year_built: dollars per year of age difference
"""

from __future__ import annotations
from typing import Optional


_DEFAULT = {
    "sqft": 150.0,
    "bathroom": 15000.0,
    "bedroom": 10000.0,
    "acre": 50000.0,
    "year_built": 1000.0,
    "finished_basement": 20000.0,
    "flood_zone": 25000.0,
    "nuisance": 15000.0,
}

# Overrides per SWIS. Numbers reflect typical 2024-2025 market conditions in
# each municipality; tweak as paired-sales data improves.
ADJUSTMENTS_BY_SWIS: dict[str, dict[str, float]] = {
    # ---------- DUTCHESS (selected hot/cold markets) ----------
    # ---------- DUTCHESS (selected hot/cold markets) ----------
    "135089": {"sqft": 220.0, "bathroom": 25000.0, "bedroom": 15000.0, "acre": 80000.0, "year_built": 1500.0, "finished_basement": 25000.0, "flood_zone": 30000.0, "nuisance": 20000.0},  # Rhinebeck town
    "135001": {"sqft": 250.0, "bathroom": 25000.0, "bedroom": 15000.0, "acre": 120000.0, "year_built": 1500.0, "finished_basement": 25000.0, "flood_zone": 30000.0, "nuisance": 20000.0},  # Rhinebeck village
    "134803": {"sqft": 220.0, "bathroom": 22000.0, "bedroom": 14000.0, "acre": 60000.0, "year_built": 1500.0},  # Tivoli
    "134889": {"sqft": 215.0, "bathroom": 22000.0, "bedroom": 14000.0, "acre": 70000.0, "year_built": 1500.0},  # Red Hook
    "134801": {"sqft": 220.0, "bathroom": 22000.0, "bedroom": 14000.0, "acre": 80000.0, "year_built": 1500.0},  # Red Hook village
    "130200": {"sqft": 280.0, "bathroom": 25000.0, "bedroom": 15000.0, "acre": 100000.0, "year_built": 1500.0},  # Beacon
    "131300": {"sqft": 175.0, "bathroom": 18000.0, "bedroom": 12000.0, "acre": 50000.0, "year_built": 1200.0},  # Poughkeepsie city
    "134689": {"sqft": 180.0, "bathroom": 18000.0, "bedroom": 12000.0, "acre": 50000.0, "year_built": 1200.0},  # Poughkeepsie town
    "133200": {"sqft": 200.0, "bathroom": 20000.0, "bedroom": 13000.0, "acre": 60000.0, "year_built": 1400.0},  # Hyde Park
    "132800": {"sqft": 195.0, "bathroom": 20000.0, "bedroom": 13000.0, "acre": 60000.0, "year_built": 1400.0},  # East Fishkill

    # ---------- ULSTER ----------
    "510800": {"sqft": 200.0, "bathroom": 20000.0, "bedroom": 13000.0, "acre": 100000.0, "year_built": 1300.0},  # Kingston city
    "513000": {"sqft": 190.0, "bathroom": 18000.0, "bedroom": 12000.0, "acre": 60000.0, "year_built": 1300.0},  # Kingston town
    "515400": {"sqft": 195.0, "bathroom": 18000.0, "bedroom": 12000.0, "acre": 60000.0, "year_built": 1300.0},  # Ulster town
    "515800": {"sqft": 280.0, "bathroom": 25000.0, "bedroom": 15000.0, "acre": 90000.0, "year_built": 1500.0},  # Woodstock
    "514801": {"sqft": 230.0, "bathroom": 22000.0, "bedroom": 14000.0, "acre": 80000.0, "year_built": 1500.0},  # Saugerties town
    "514889": {"sqft": 240.0, "bathroom": 23000.0, "bedroom": 14000.0, "acre": 90000.0, "year_built": 1500.0},  # Saugerties village
    "513801": {"sqft": 260.0, "bathroom": 25000.0, "bedroom": 15000.0, "acre": 80000.0, "year_built": 1500.0},  # New Paltz town
    "513889": {"sqft": 280.0, "bathroom": 28000.0, "bedroom": 16000.0, "acre": 100000.0, "year_built": 1500.0},  # New Paltz village
    "513200": {"sqft": 210.0, "bathroom": 20000.0, "bedroom": 13000.0, "acre": 70000.0, "year_built": 1400.0},  # Lloyd
    "513400": {"sqft": 220.0, "bathroom": 22000.0, "bedroom": 14000.0, "acre": 70000.0, "year_built": 1400.0},  # Marbletown
    "512200": {"sqft": 210.0, "bathroom": 20000.0, "bedroom": 13000.0, "acre": 60000.0, "year_built": 1400.0},  # Esopus
    "512800": {"sqft": 230.0, "bathroom": 22000.0, "bedroom": 14000.0, "acre": 70000.0, "year_built": 1500.0},  # Hurley
    "514600": {"sqft": 215.0, "bathroom": 21000.0, "bedroom": 13000.0, "acre": 70000.0, "year_built": 1400.0},  # Rosendale
}


def get_adjustments(sbl_or_swis: Optional[str]) -> dict[str, float]:
    """Return adjustment dict for the SWIS embedded in the SBL/SWIS string,
    falling back to _DEFAULT for unknown municipalities."""
    if not sbl_or_swis:
        return dict(_DEFAULT)
    swis = sbl_or_swis[:6]
    return dict(ADJUSTMENTS_BY_SWIS.get(swis, _DEFAULT))
