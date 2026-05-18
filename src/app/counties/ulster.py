import re
import requests
from app.counties.base import CountyInterface
from app.exceptions import CountyAPIError
from app.logging_safe import safe_addr

NYS_PARCELS_URL = "https://gisservices.its.ny.gov/arcgis/rest/services/NYS_Tax_Parcels_Public/MapServer/1/query"

ULSTER_SWIS_MAP = {
    "510800": "Kingston",   "512000": "Denning",     "512200": "Esopus",
    "512400": "Gardiner",   "512600": "Hardenburgh", "512800": "Hurley",
    "513000": "Kingston",   "513200": "Lloyd",       "513400": "Marbletown",
    "513600": "Marlborough","513801": "New Paltz",   "513889": "New Paltz",
    "514000": "Olive",      "514200": "Plattekill",  "514400": "Rochester",
    "514600": "Rosendale",  "514801": "Saugerties",  "514889": "Saugerties",
    "515000": "Shandaken",  "515200": "Shawangunk",  "515400": "Ulster",
    "515601": "Wawarsing",  "515689": "Wawarsing",   "515800": "Woodstock",
}


def _escape(value: str) -> str:
    """Escape single quotes for ArcGIS WHERE clauses."""
    return value.replace("'", "''")


class UlsterCounty(CountyInterface):
    """
    Ulster County handler backed by the NYS Tax Parcels Public FeatureServer.
    Identifier convention: SWIS + SBL concatenated (matches Dutchess shape).
    """

    def __init__(self, timeout: int = 20):
        """Timeout controls how long we wait on the NYS GIS service.

        Use 20s for the initial subject lookup (user is willing to wait once);
        construct with a smaller value (e.g. 3-4s) for per-comp verification
        loops where one slow query would multiply across dozens of calls.
        """
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "TaxGrieveNY/1.0 (https://github.com/jwlehane/griever)",
        })
        self.swis_map = ULSTER_SWIS_MAP
        self.timeout = timeout

    def search_address(self, address_string: str, preferred_swis: str = None) -> dict:
        raw = address_string.upper().strip()
        # Take only the street-part (before first comma) for the PARCEL_ADDR match.
        head = raw.split(",")[0].strip()
        match_num = re.match(r"^(\d+)\s+(.+)$", head)
        if not match_num:
            return None
        number, street = match_num.group(1), match_num.group(2).strip()

        # Town hint (post-comma) — narrows query when provided.
        town_hint = None
        parts = [p.strip() for p in raw.split(",")]
        if len(parts) >= 2:
            for known in self.swis_map.values():
                if known.upper() in parts[1]:
                    town_hint = known
                    break

        # NYS PARCEL_ADDR concatenates "<number> <street>" — single field LIKE
        # against this is more robust than splitting LOC_ST_NBR + LOC_STREET.
        addr_prefix = f"{number} {street}".replace("'", "''")
        where_parts = [
            "COUNTY_NAME='Ulster'",
            f"UPPER(PARCEL_ADDR) LIKE '{addr_prefix}%'",
        ]
        if town_hint:
            where_parts.append(f"UPPER(CITYTOWN_NAME)='{_escape(town_hint.upper())}'")

        params = {
            "where": " AND ".join(where_parts),
            "outFields": "PARCEL_ADDR,SWIS,SBL,CITYTOWN_NAME,MUNI_NAME",
            "returnGeometry": "false",
            "resultRecordCount": 1,
            "f": "json",
        }
        try:
            resp = self.session.get(NYS_PARCELS_URL, params=params, timeout=self.timeout)
            resp.raise_for_status()
            feats = resp.json().get("features", []) or []
        except requests.RequestException as e:
            raise CountyAPIError(
                "NYS Tax Parcels service is unreachable. Try again in a minute."
            ) from e

        if not feats:
            print(f"  Ulster NOT FOUND for {safe_addr(f'{number} {street}')}")
            return None

        attrs = feats[0]["attributes"]
        swis = attrs.get("SWIS", "")
        sbl = attrs.get("SBL", "")
        identifier = f"{swis}{sbl}"
        print(f"  Ulster FOUND {safe_addr(attrs.get('PARCEL_ADDR'))} in {attrs.get('CITYTOWN_NAME')}")
        return {
            "parcelgrid": identifier,
            "swis": swis,
            "sbl": sbl,
            "address": attrs.get("PARCEL_ADDR"),
            "town": attrs.get("CITYTOWN_NAME"),
        }

    def get_full_rps_data(self, identifier: str) -> dict:
        # identifier is SWIS(6) + SBL. SBL field in NYS service holds the SBL portion.
        swis = identifier[:6]
        sbl = identifier[6:]
        where = f"COUNTY_NAME='Ulster' AND SWIS='{_escape(swis)}' AND SBL='{_escape(sbl)}'"
        params = {
            "where": where,
            "outFields": "*",
            "returnGeometry": "false",
            "f": "json",
        }
        try:
            resp = self.session.get(NYS_PARCELS_URL, params=params, timeout=self.timeout)
            resp.raise_for_status()
            feats = resp.json().get("features", [])
            if not feats:
                return None
            a = feats[0]["attributes"]

            full_baths = a.get("NBR_FULL_BATHS") or 0
            # NYS service does not expose half-baths; approximate with full_baths only.
            bathrooms = float(full_baths)

            address = a.get("PARCEL_ADDR") or " ".join(
                [s for s in [a.get("LOC_ST_NBR"), a.get("LOC_STREET")] if s]
            ).strip()

            return {
                "address": (address or "").title(),
                "sbl": identifier,
                "sqft": float(a.get("SQFT_LIVING") or 0),
                "acreage": float(a.get("ACRES") or a.get("CALC_ACRES") or 0),
                "bedrooms": int(a.get("NBR_BEDROOMS") or 0),
                "bathrooms": bathrooms,
                "year_built": int(a.get("YR_BLT") or 0),
                "assessment_2026": float(a.get("TOTAL_AV") or 0),
                "assessment_2025": 0.0,
                "property_class": (a.get("PROP_CLASS") or "").strip(),
            }
        except requests.RequestException as e:
            raise CountyAPIError(f"Ulster RPS fetch failed for {identifier}: {e}")

    def get_town_from_identifier(self, identifier: str) -> str:
        swis = identifier[:6]
        return self.swis_map.get(swis, "Kingston")
