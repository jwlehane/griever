"""NYS ORPTS property class code mapping.

Source: NYS ORPTS Assessor's Manual, Volume 2: Property Type Classification.
We map the 3-digit code to a coarse RapidAPI/Zillow `homeType` value so we can
filter comparable sales to match the subject's class.

Classes 200–299 are residential. 210 = One-family year-round, which is by far
the most common single-family case. Multi-family (220, 230) and rural (240,
250) are also residential but require separate comp pools.
"""

from __future__ import annotations
from typing import Optional


# 3-digit NYS class → RapidAPI homeType.
_CLASS_TO_HOMETYPE: dict[str, str] = {
    "210": "SINGLE_FAMILY",   # One Family Year-Round Residence
    "215": "SINGLE_FAMILY",   # One Family Year-Round Residence with Accessory Apartment
    "240": "SINGLE_FAMILY",   # Rural Residence with Acreage
    "241": "SINGLE_FAMILY",   # Primarily residential, also used in agriculture
    "250": "SINGLE_FAMILY",   # Estate
    "270": "MANUFACTURED",    # Manufactured / mobile
    "280": "SINGLE_FAMILY",   # Residential — multi-purpose / multi-structure
    "411": "MULTI_FAMILY",    # Apartment
    "220": "MULTI_FAMILY",    # Two Family Year-Round Residence
    "230": "MULTI_FAMILY",    # Three Family Year-Round Residence
    "411 (cooperative)": "CONDO",
    "411C": "CONDO",
    "411-D": "CONDO",
}


def expected_hometype(nys_class: Optional[str]) -> Optional[str]:
    """Map a NYS property_class string (e.g. '210') to RapidAPI homeType.

    Returns None when class is unknown or non-residential — callers should
    treat this as "do not filter" rather than "filter to nothing".
    """
    if not nys_class:
        return None
    code = str(nys_class).strip().split()[0]  # take leading code if "210 - One Family"
    return _CLASS_TO_HOMETYPE.get(code)


def is_residential(nys_class: Optional[str]) -> bool:
    """True if the class falls in residential ranges 200–299 (or 411 apartment)."""
    if not nys_class:
        return True  # don't reject when we don't know
    code = str(nys_class).strip().split()[0]
    try:
        n = int(code[:3])
    except (ValueError, TypeError):
        return True
    return 200 <= n <= 299 or n in (411,)
