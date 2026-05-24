"""Pluggable comp-source layer.

Two backends:
- RapidAPI (current default) — live Zillow data via real-time-real-estate-data.
  Working today, but the legal/ToS verdict on persisting and republishing this
  data is pending (see project_griever_legal in auto-memory).
- ORPTS — NYS Office of Real Property Tax Services. Public-domain RP-5217
  sales file, ~3-month lag. The license-clean fallback if counsel rejects
  RapidAPI persistence (see project_griever_orpts).

Switch with the COMP_SOURCE env var: 'rapidapi' (default) or 'orpts'.

The ORPTS path is a SCAFFOLD only — it returns an empty list and logs that
the source is selected. A real implementation needs:
1. A bulk download + transform of the RP-5217 file into a local sales_archive
   table (one-time + monthly refresh, not per-request).
2. A spatial/SWIS-based query that returns recent sold parcels near the subject.
3. Field mapping from RP-5217 columns to the same shape RapidAPI returns
   (price, date, sqft, beds/baths, year_built, lat/lon, parcel id).
That work is gated on the counsel verdict — no point implementing the ingest
if RapidAPI persistence turns out to be allowed.
"""

from __future__ import annotations

import os


def selected_source() -> str:
    """Return the configured comp source name, lowercased. Defaults to 'rapidapi'."""
    return (os.getenv("COMP_SOURCE") or "rapidapi").strip().lower()


def is_orpts() -> bool:
    return selected_source() == "orpts"


def fetch_orpts_sold(location: str, beds_min, beds_max, swis: str | None = None) -> list[dict]:
    """Placeholder for the ORPTS sold-sales lookup.

    Returns an empty list today. When implemented, must return a list of
    dicts shaped like the RapidAPI sold-listing payload so the calling code
    in TaxGrieveCore.discover_comps_live needs minimal changes:

        {
            'address': str,
            'parcelNumber': str,         # SWIS+SBL concatenated
            'price': float,
            'dateSold': int,             # epoch ms
            'livingArea': int,           # sqft
            'lotAreaValue': float,       # acres or sqft (set lotAreaUnit)
            'lotAreaUnit': str,
            'bedrooms': int,
            'bathrooms': float,
            'yearBuilt': int | None,
            'latitude': float,
            'longitude': float,
        }
    """
    print(f"comp_source: ORPTS selected but ingest not yet implemented "
          f"(location={location}, beds={beds_min}-{beds_max}, swis={swis}); returning empty list.")
    return []
