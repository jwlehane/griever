from app.counties.dutchess import DutchessCounty
from app.counties.ulster import UlsterCounty, ULSTER_SWIS_MAP

# Lowercased town names by county (for routing by address text).
_ULSTER_TOWNS = {name.lower() for name in ULSTER_SWIS_MAP.values()}
_ULSTER_SWIS_PREFIXES = set(ULSTER_SWIS_MAP.keys())

# Common Ulster ZIPs (best-effort; some straddle county lines).
_ULSTER_ZIPS = {
    "12401", "12402", "12404", "12409", "12410", "12411", "12412", "12416",
    "12419", "12420", "12421", "12428", "12429", "12432", "12433", "12435",
    "12440", "12443", "12446", "12449", "12453", "12456", "12457", "12458",
    "12461", "12464", "12465", "12466", "12471", "12472", "12474", "12477",
    "12480", "12481", "12483", "12484", "12486", "12487", "12489", "12491",
    "12493", "12494", "12495", "12498", "12525", "12528", "12542", "12547",
    "12548", "12561", "12566", "12575", "12589",
}


def _detect_county(address_string: str = None, zip_code: str = None, sbl: str = None) -> str:
    """Return 'ulster' or 'dutchess'. Defaults to dutchess for backward compat.

    SBL takes precedence — it carries the SWIS code which is the authoritative
    geo identifier for a parcel. Without SBL, falls back to ZIP, then address text.
    """
    if sbl and len(sbl) >= 6 and sbl[:6] in _ULSTER_SWIS_PREFIXES:
        return "ulster"
    if zip_code and zip_code[:5] in _ULSTER_ZIPS:
        return "ulster"
    if address_string:
        s = address_string.lower()
        if "ulster county" in s:
            return "ulster"
        for town in _ULSTER_TOWNS:
            if f" {town}" in s or s.startswith(town) or f",{town}" in s.replace(", ", ",") or f", {town}" in s:
                return "ulster"
        m = [tok for tok in s.replace(",", " ").split() if tok.isdigit() and len(tok) == 5]
        if m and m[-1] in _ULSTER_ZIPS:
            return "ulster"
    return "dutchess"


class CountyFactory:
    @staticmethod
    def get_county_handler(address_string: str = None, zip_code: str = None, sbl: str = None):
        """Return the correct county API handler. Pass `sbl` when available
        (e.g. once a subject's parcel has been resolved) — SBL routing is
        authoritative, address-text routing is best-effort."""
        county = _detect_county(address_string, zip_code, sbl)
        if county == "ulster":
            return UlsterCounty()
        return DutchessCounty()

    @staticmethod
    def detect_county(address_string: str = None, zip_code: str = None, sbl: str = None) -> str:
        return _detect_county(address_string, zip_code, sbl)
