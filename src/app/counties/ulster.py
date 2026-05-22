import re
import requests
from app.counties.base import CountyInterface
from app.exceptions import CountyAPIError
from app.logging_safe import safe_addr

NYS_PARCELS_URL = "https://gisservices.its.ny.gov/arcgis/rest/services/NYS_Tax_Parcels_Public/MapServer/1/query"
ULSTER_PARCELS_URL = "https://gis.ulstercountyny.gov/server/rest/services/Parcel_Viewer/Tax_Parcel_Data/MapServer/0/query"

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

_SUFFIX_PAIRS = [
    ("STREET", "ST"),
    ("ROAD", "RD"),
    ("AVENUE", "AVE"),
    ("DRIVE", "DR"),
    ("LANE", "LN"),
    ("COURT", "CT"),
    ("PLACE", "PL"),
    ("TURNPIKE", "TPKE"),
    ("BOULEVARD", "BLVD"),
]


def _escape(value: str) -> str:
    """Escape single quotes for ArcGIS WHERE clauses."""
    return value.replace("'", "''")


def _street_options(street: str) -> list[str]:
    clean = re.sub(r"\s+", " ", (street or "").upper().strip())
    options = [clean]
    for long, short in _SUFFIX_PAIRS:
        for suffix in (long, short):
            token = f" {suffix}"
            if clean.endswith(token):
                base = clean[: -len(token)].strip()
                options.extend([f"{base} {short}", f"{base} {long}", base])
                break
    seen = set()
    return [opt for opt in options if opt and not (opt in seen or seen.add(opt))]


def _county_identifier(attrs: dict) -> str:
    return (attrs.get("RPS_Link") or "").strip()


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

        feats = []
        for street_opt in _street_options(street):
            # Ulster's county parcel service responds much faster than the
            # statewide service and exposes RPS_Link as the full SWIS+SBL ID.
            addr_prefix = f"{number} {street_opt}".replace("'", "''")
            where_parts = [
                f"PARCEL_ADDRESS LIKE '{addr_prefix.title()}%'",
            ]
            if town_hint:
                where_parts.append(f"PARCEL_CITY='{_escape(town_hint)}'")
            if preferred_swis:
                where_parts.append(f"SWIS_CODE='{_escape(preferred_swis)}'")

            params = {
                "where": " AND ".join(where_parts),
                "outFields": "PARCEL_ADDRESS,PARCEL_CITY,SWIS_CODE,PRINTKEY,RPS_Link",
                "returnGeometry": "false",
                "resultRecordCount": 1,
                "f": "json",
            }
            try:
                resp = self.session.get(ULSTER_PARCELS_URL, params=params, timeout=min(self.timeout, 8))
                resp.raise_for_status()
                feats = resp.json().get("features", []) or []
                if feats:
                    break
            except requests.RequestException as e:
                raise CountyAPIError(
                    "Ulster County parcel service is unreachable. Try again in a minute."
                ) from e

        if not feats:
            print(f"  Ulster NOT FOUND for {safe_addr(f'{number} {street}')}")
            return None

        attrs = feats[0]["attributes"]
        swis = attrs.get("SWIS_CODE", "")
        identifier = _county_identifier(attrs)
        print(f"  Ulster FOUND {safe_addr(attrs.get('PARCEL_ADDRESS'))} in {attrs.get('PARCEL_CITY')}")
        return {
            "parcelgrid": identifier,
            "swis": swis,
            "sbl": identifier,
            "address": attrs.get("PARCEL_ADDRESS"),
            "town": attrs.get("PARCEL_CITY"),
        }

    def suggest_addresses(self, address_string: str, limit: int = 8) -> list[dict]:
        raw = address_string.upper().strip()
        head = raw.split(",")[0].strip()
        match_num = re.match(r"^(\d+)\s+(.+)$", head)
        if not match_num:
            return []
        number, street = match_num.group(1), match_num.group(2).strip()

        town_hint = None
        parts = [p.strip() for p in raw.split(",")]
        if len(parts) >= 2:
            for known in self.swis_map.values():
                if known.upper() in parts[1]:
                    town_hint = known
                    break

        suggestions = []
        seen = set()
        for street_opt in _street_options(street):
            addr_prefix = f"{number} {street_opt}".replace("'", "''")
            where_parts = [
                f"PARCEL_ADDRESS LIKE '{addr_prefix.title()}%'",
            ]
            if town_hint:
                where_parts.append(f"PARCEL_CITY='{_escape(town_hint)}'")
            params = {
                "where": " AND ".join(where_parts),
                "outFields": "PARCEL_ADDRESS,PARCEL_CITY,SWIS_CODE,PRINTKEY,RPS_Link",
                "returnGeometry": "false",
                "resultRecordCount": limit,
                "f": "json",
            }
            resp = self.session.get(ULSTER_PARCELS_URL, params=params, timeout=min(self.timeout, 8))
            resp.raise_for_status()
            feats = resp.json().get("features", []) or []
            for feat in feats:
                attrs = feat.get("attributes", {}) or {}
                swis = attrs.get("SWIS_CODE", "")
                identifier = _county_identifier(attrs)
                if not identifier or identifier in seen:
                    continue
                seen.add(identifier)
                suggestions.append({
                    "address": (attrs.get("PARCEL_ADDRESS") or "").title(),
                    "town": attrs.get("PARCEL_CITY") or self.get_town_from_identifier(identifier),
                    "county": "Ulster",
                    "parcelgrid": identifier,
                    "sbl": identifier,
                    "swis": swis,
                })
                if len(suggestions) >= limit:
                    return suggestions
        return suggestions

    def get_full_rps_data(self, identifier: str) -> dict:
        county_profile = self._get_county_parcel_profile(identifier)
        if county_profile:
            return county_profile

        # Fallback for older identifiers that are only present in the statewide
        # service. The county service is preferred because the statewide
        # endpoint is often slow enough to break the user-facing flow.
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

    def _get_county_parcel_profile(self, identifier: str) -> dict:
        params = {
            "where": f"RPS_Link='{_escape(identifier)}'",
            "outFields": "PARCEL_ADDRESS,PARCEL_CITY,SWIS_CODE,PRINTKEY,RPS_Link,ACRES,PROP_CLASS,PROP_CLASS_CODE",
            "returnGeometry": "false",
            "resultRecordCount": 1,
            "f": "json",
        }
        try:
            resp = self.session.get(ULSTER_PARCELS_URL, params=params, timeout=min(self.timeout, 8))
            resp.raise_for_status()
            feats = resp.json().get("features", []) or []
            if not feats:
                return None
            a = feats[0]["attributes"]
            prop_class = (a.get("PROP_CLASS_CODE") or a.get("PROP_CLASS") or "").strip()
            return {
                "address": (a.get("PARCEL_ADDRESS") or "").title(),
                "sbl": identifier,
                "sqft": 0.0,
                "acreage": float(a.get("ACRES") or 0),
                "bedrooms": 0,
                "bathrooms": 0.0,
                "year_built": 0,
                "assessment_2026": 0.0,
                "assessment_2025": 0.0,
                "property_class": prop_class,
            }
        except requests.RequestException as e:
            raise CountyAPIError(f"Ulster parcel fetch failed for {identifier}: {e}")

    def get_town_from_identifier(self, identifier: str) -> str:
        swis = identifier[:6]
        return self.swis_map.get(swis, "Kingston")
