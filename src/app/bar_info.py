"""Board of Assessment Review (BAR) routing & deadlines.

In NY, RP-524 grievance complaints are filed with the BAR of the municipality
that assesses the property. Grievance Day is set by RPTL §512; the default
is the 4th Tuesday in May, but many municipalities choose a different date.

Keys are SWIS prefixes (first 6 chars of SBL). Verify dates with the local
assessor before filing — this data should be refreshed annually.
"""

from __future__ import annotations
from typing import Optional


# Default fallback when we don't have specific info
_DEFAULT_GRIEVANCE_DAY = "4th Tuesday in May"


BAR_BY_SWIS: dict[str, dict] = {
    # ---------- DUTCHESS COUNTY ----------
    "132000": {  # Amenia
        "municipality": "Town of Amenia",
        "grievance_day": "Tuesday, May 26, 2026",
        "bar_address": "Town of Amenia Town Hall\n4988 Route 22\nAmenia, NY 12501",
        "submission_method": "In person, 4–8 pm, or by appointment",
        "phone": "(845) 373-8118",
        "assessor": "Sole Assessor",
    },
    "130200": {  # Beacon (city)
        "municipality": "City of Beacon",
        "grievance_day": "Tuesday, February 17, 2026 (cities differ)",
        "bar_address": "Beacon City Hall\n1 Municipal Plaza\nBeacon, NY 12508",
        "submission_method": "In person or by mail. City BAR meets 3rd Tuesday in February.",
        "phone": "(845) 838-5009",
        "notes": "Cities in Dutchess have different Grievance Days than towns — verify with assessor.",
    },
    "132200": {  # Beekman
        "municipality": "Town of Beekman",
        "grievance_day": "Tuesday, May 26, 2026",
        "bar_address": "Town of Beekman Town Hall\n4 Main Street\nPoughquag, NY 12570",
        "submission_method": "In person, 4–8 pm",
        "phone": "(845) 724-4082",
    },
    "132400": {  # Clinton
        "municipality": "Town of Clinton",
        "grievance_day": "Tuesday, May 26, 2026",
        "bar_address": "Town of Clinton Town Hall\n1215 Centre Road\nRhinebeck, NY 12572",
        "submission_method": "In person or by mail",
        "phone": "(845) 266-5721",
    },
    "133200": {  # Hyde Park
        "municipality": "Town of Hyde Park",
        "grievance_day": "Tuesday, May 26, 2026",
        "bar_address": "Town of Hyde Park Town Hall\n4383 Albany Post Road\nHyde Park, NY 12538",
        "submission_method": "In person, 4–8 pm; mail accepted if postmarked by deadline",
        "phone": "(845) 229-5111",
    },
    "131300": {  # Poughkeepsie (city)
        "municipality": "City of Poughkeepsie",
        "grievance_day": "Tuesday, February 17, 2026 (cities differ)",
        "bar_address": "Poughkeepsie City Hall — Assessor's Office\n62 Civic Center Plaza\nPoughkeepsie, NY 12601",
        "submission_method": "In person or by mail",
        "phone": "(845) 451-4042",
        "notes": "Cities follow a different calendar than towns.",
    },
    "134689": {  # Poughkeepsie (town)
        "municipality": "Town of Poughkeepsie",
        "grievance_day": "Tuesday, May 26, 2026",
        "bar_address": "Town of Poughkeepsie Town Hall\n1 Overocker Road\nPoughkeepsie, NY 12603",
        "submission_method": "In person, 4–8 pm",
        "phone": "(845) 485-3613",
    },
    "135089": {  # Rhinebeck (town)
        "municipality": "Town of Rhinebeck",
        "grievance_day": "Tuesday, May 26, 2026",
        "bar_address": "Town of Rhinebeck Town Hall\n80 East Market Street\nRhinebeck, NY 12572",
        "submission_method": "In person, 4–8 pm; mail accepted if postmarked by Grievance Day",
        "phone": "(845) 876-3409",
    },
    "135001": {  # Rhinebeck (village)
        "municipality": "Village of Rhinebeck (assessed by Town)",
        "grievance_day": "Tuesday, May 26, 2026",
        "bar_address": "Town of Rhinebeck Town Hall\n80 East Market Street\nRhinebeck, NY 12572",
        "submission_method": "In person, 4–8 pm; mail accepted if postmarked by Grievance Day",
        "phone": "(845) 876-3409",
        "notes": "Village assessments are merged with the Town of Rhinebeck roll.",
    },
    "134889": {  # Red Hook
        "municipality": "Town of Red Hook",
        "grievance_day": "Tuesday, May 26, 2026",
        "bar_address": "Town of Red Hook Town Hall\n7340 South Broadway\nRed Hook, NY 12571",
        "submission_method": "In person, 4–8 pm",
        "phone": "(845) 758-5440",
    },
    "133089": {  # Fishkill (town)
        "municipality": "Town of Fishkill",
        "grievance_day": "Tuesday, May 26, 2026",
        "bar_address": "Town of Fishkill Town Hall\n807 Route 52\nFishkill, NY 12524",
        "submission_method": "In person, 4–8 pm",
        "phone": "(845) 831-7800",
    },
    "132800": {  # East Fishkill
        "municipality": "Town of East Fishkill",
        "grievance_day": "Tuesday, May 26, 2026",
        "bar_address": "Town of East Fishkill Town Hall\n330 Route 376\nHopewell Junction, NY 12533",
        "submission_method": "In person, 4–8 pm",
        "phone": "(845) 226-3539",
    },

    # ---------- ULSTER COUNTY ----------
    "510800": {  # Kingston (city)
        "municipality": "City of Kingston",
        "grievance_day": "Tuesday, May 26, 2026",
        "bar_address": "City of Kingston Assessor's Office\nCity Hall, 420 Broadway\nKingston, NY 12401",
        "submission_method": "In person, 4–8 pm; mail accepted if postmarked by Grievance Day",
        "phone": "(845) 334-3934",
        "notes": "Kingston completed a citywide revaluation in 2024 (RAR 44.03%).",
    },
    "513000": {  # Kingston (town)
        "municipality": "Town of Kingston",
        "grievance_day": "Tuesday, May 26, 2026",
        "bar_address": "Town of Kingston Town Hall\n906 Sawkill Road\nKingston, NY 12401",
        "submission_method": "In person, 4–8 pm",
        "phone": "(845) 336-8853",
    },
    "512800": {  # Hurley
        "municipality": "Town of Hurley",
        "grievance_day": "Tuesday, May 26, 2026",
        "bar_address": "Town of Hurley Town Hall\n10 Wamsley Place\nHurley, NY 12443",
        "submission_method": "In person, 4–8 pm",
        "phone": "(845) 331-7474",
    },
    "513801": {  # New Paltz (town)
        "municipality": "Town of New Paltz",
        "grievance_day": "Tuesday, May 26, 2026",
        "bar_address": "Town of New Paltz Town Hall\n1 Veterans Drive\nNew Paltz, NY 12561",
        "submission_method": "In person, 4–8 pm; mail accepted if postmarked by Grievance Day",
        "phone": "(845) 255-0103",
    },
    "513889": {  # New Paltz (village)
        "municipality": "Village of New Paltz (assessed by Town)",
        "grievance_day": "Tuesday, May 26, 2026",
        "bar_address": "Town of New Paltz Town Hall\n1 Veterans Drive\nNew Paltz, NY 12561",
        "submission_method": "In person, 4–8 pm; mail accepted if postmarked by Grievance Day",
        "phone": "(845) 255-0103",
        "notes": "Village assessments are merged with the Town of New Paltz roll.",
    },
    "514801": {  # Saugerties (town)
        "municipality": "Town of Saugerties",
        "grievance_day": "Tuesday, May 26, 2026",
        "bar_address": "Town of Saugerties Town Hall\n4 High Street\nSaugerties, NY 12477",
        "submission_method": "In person, 4–8 pm",
        "phone": "(845) 246-2800",
    },
    "515800": {  # Woodstock
        "municipality": "Town of Woodstock",
        "grievance_day": "Tuesday, May 26, 2026",
        "bar_address": "Town of Woodstock Town Hall\n45 Comeau Drive\nWoodstock, NY 12498",
        "submission_method": "In person, 4–8 pm",
        "phone": "(845) 679-2113",
    },
    "513200": {  # Lloyd
        "municipality": "Town of Lloyd",
        "grievance_day": "Tuesday, May 26, 2026",
        "bar_address": "Town of Lloyd Town Hall\n12 Church Street\nHighland, NY 12528",
        "submission_method": "In person, 4–8 pm",
        "phone": "(845) 691-2144",
    },
}


def get_bar(sbl_or_swis: Optional[str]) -> Optional[dict]:
    """Return BAR contact info for the municipality identified by the SWIS
    prefix. None when unknown.
    """
    if not sbl_or_swis:
        return None
    swis = sbl_or_swis[:6]
    return BAR_BY_SWIS.get(swis)
