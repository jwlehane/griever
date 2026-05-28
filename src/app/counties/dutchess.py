import requests
import re
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from app.counties.base import CountyInterface
from app.exceptions import CountyAPIError
from app.logging_safe import safe_addr

API_BASE_URL = "https://gis.dutchessny.gov/parcelaccess/asp"

_DIRECTION_WORDS = {
    "NORTH": "N",
    "SOUTH": "S",
    "EAST": "E",
    "WEST": "W",
}

_SUFFIXES = [
    " STREET", " ST", " ROAD", " RD", " AVENUE", " AVE", " DRIVE", " DR",
    " LANE", " LN", " COURT", " CT", " PLACE", " PL", " TURNPIKE", " TPKE",
    " BOULEVARD", " BLVD",
]

_CANONICAL_SUFFIXES = {
    "STREET": "ST", "ST": "ST",
    "ROAD": "RD", "RD": "RD",
    "AVENUE": "AVE", "AVE": "AVE",
    "DRIVE": "DR", "DR": "DR",
    "LANE": "LN", "LN": "LN",
    "COURT": "CT", "CT": "CT",
    "PLACE": "PL", "PL": "PL",
    "TURNPIKE": "TPKE", "TPKE": "TPKE",
    "BOULEVARD": "BLVD", "BLVD": "BLVD",
}


def _get_f(source, key, default=""):
    return source.get(key, source.get(key.lower(), source.get(key.upper(), default)))


def _clean_street_parts(street_part: str):
    clean_street = re.sub(r"\s+", " ", (street_part or "").upper().strip())
    
    # 1. Strip suffix first
    street_base = clean_street
    suffix_found = None
    for suffix in _SUFFIXES:
        if clean_street.endswith(suffix):
            street_base = clean_street[:len(clean_street)-len(suffix)].strip()
            suffix_found = suffix
            break

    # 2. Extract and replace direction prefix if it is followed by a space
    predir = ""
    street_no_dir = street_base
    for word, abbr in _DIRECTION_WORDS.items():
        if street_base.startswith(f"{word} "):
            street_no_dir = street_base[len(word) + 1:].strip()
            predir = abbr
            break
        elif street_base.startswith(f"{abbr} "):
            street_no_dir = street_base[2:].strip()
            predir = abbr
            break

    # 3. Reconstruct cleaned forms
    if predir:
        street_base = f"{predir} {street_no_dir}"
        clean_street = f"{street_base}{suffix_found}" if suffix_found else street_base
    else:
        street_base = street_no_dir
        clean_street = f"{street_base}{suffix_found}" if suffix_found else street_base

    street_options = [clean_street, street_base]
    if street_no_dir != street_base:
        street_options.append(street_no_dir)
    compact_source = street_no_dir
    compact = compact_source.replace(" ", "")
    if len(compact_source.split()) > 1 and compact:
        street_options.append(compact)

    seen = set()
    return predir, [x for x in street_options if x and not (x in seen or seen.add(x))]



class DutchessCounty(CountyInterface):
    def __init__(self):
        self.session = requests.Session()
        # Initialize session to get cookies if necessary
        try:
            self.session.get("https://gis.dutchessny.gov/parcelaccess/", timeout=5)
        except requests.RequestException:
            pass
        self.headers = {
            "Referer": "https://gis.dutchessny.gov/parcelaccess/",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        self.swis_map = {
            "132000": "Amenia", "130200": "Beacon", "132200": "Beekman", "132400": "Clinton",
            "132600": "Dover", "132800": "East Fishkill", "133089": "Fishkill", "133001": "Fishkill",
            "133200": "Hyde Park", "133400": "LaGrange", "133600": "Milan", "135801": "Millbrook",
            "133801": "Millerton", "133889": "North East", "134089": "Pawling", "134001": "Pawling",
            "134200": "Pine Plains", "134400": "Pleasant Valley", "134689": "Poughkeepsie", "131300": "Poughkeepsie",
            "134889": "Red Hook", "134801": "Red Hook", "135089": "Rhinebeck", "135001": "Rhinebeck",
            "135200": "Stanford", "134803": "Tivoli", "135400": "Union Vale", "135689": "Wappinger",
            "135889": "Washington"
        }

    @retry(
        stop=stop_after_attempt(3), 
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((requests.RequestException, CountyAPIError))
    )
    def search_address(self, address_string: str, preferred_swis: str = None) -> dict:
        """Finds parcel info with strict town filtering and console logging."""
        raw_input = address_string.upper().strip()
        
        match_num = re.match(r'^(\d+)', raw_input)
        if not match_num: return None
        number = match_num.group(1)
        
        street_part = raw_input[len(number):].split(',')[0].strip()
        
        predir, street_options = _clean_street_parts(street_part)
        clean_street = street_options[0]

        # --- OPTIMIZED SWIS SELECTION ---
        swis_options = []
        
        # 1. If preferred_swis is provided (subject's town), ONLY check that.
        if preferred_swis:
            swis_options = [preferred_swis]
        else:
            # 2. Check if input contains a specific town name
            # Gather ALL matching SWIS codes (e.g. Rhinebeck has 135089 AND 135001)
            for code, name in self.swis_map.items():
                if name.upper() in raw_input:
                    swis_options.append(code)
            
            # 3. Last Resort: Search everything (only if no town info at all)
            if not swis_options:
                swis_options = list(self.swis_map.keys())

        # Check if the user specified a suffix to validate
        expected_suffix = None
        for suffix in _SUFFIXES:
            if street_part.upper().endswith(suffix):
                expected_suffix = _CANONICAL_SUFFIXES.get(suffix.strip())
                break

        print(f"DEBUG: Searching {safe_addr(f'{number} {clean_street}')} in {len(swis_options)} towns...")

        for s in swis_options:
            town_name = self.swis_map.get(s, s)
            for st in street_options:
                # Try with extracted predir
                params = {'number': number, 'street': st.strip(), 'predir': predir, 'swis': s}
                try:
                    # Low timeout for verified town searches
                    resp = self.session.get(f"{API_BASE_URL}/search_extract_addresses.asp", params=params, headers=self.headers, timeout=5)
                    resp.raise_for_status()
                    data = resp.json()
                    if data.get('success') and data.get('data'):
                        res = data['data'][0]
                        # Suffix verification
                        res_suff_raw = (res.get('Loc_mail_st_suff') or res.get('loc_mail_st_suff') or '').strip().upper()
                        res_suff = _CANONICAL_SUFFIXES.get(res_suff_raw, res_suff_raw)
                        if expected_suffix and res_suff and res_suff != expected_suffix:
                            continue
                        # Ensure key consistency
                        if 'parcelgrid' not in res and 'id' in res: res['parcelgrid'] = res['id']
                        print(f"  FOUND in {town_name}")
                        return res
                except:
                    pass
                
                # If predir was used and failed, also try WITHOUT predir for this street option
                if predir:
                    params_no_dir = {'number': number, 'street': st.strip(), 'swis': s}
                    try:
                        resp = self.session.get(f"{API_BASE_URL}/search_extract_addresses.asp", params=params_no_dir, headers=self.headers, timeout=5)
                        resp.raise_for_status()
                        data = resp.json()
                        if data.get('success') and data.get('data'):
                            res = data['data'][0]
                            # Suffix verification
                            res_suff_raw = (res.get('Loc_mail_st_suff') or res.get('loc_mail_st_suff') or '').strip().upper()
                            res_suff = _CANONICAL_SUFFIXES.get(res_suff_raw, res_suff_raw)
                            if expected_suffix and res_suff and res_suff != expected_suffix:
                                continue
                            if 'parcelgrid' not in res and 'id' in res: res['parcelgrid'] = res['id']
                            print(f"  FOUND in {town_name} (no predir)")
                            return res
                    except:
                        pass
        print(f"  NOT FOUND")
        return None

    def suggest_addresses(self, address_string: str, limit: int = 8, swis_options: list[str] = None) -> list[dict]:
        """Return parcel-backed address suggestions for autocomplete."""
        raw_input = address_string.upper().strip()
        match_num = re.match(r'^(\d+)', raw_input)
        if not match_num:
            return []

        number = match_num.group(1)
        street_part = raw_input[len(number):].split(',')[0].strip()
        if len(street_part) < 3:
            return []

        predir, street_options = _clean_street_parts(street_part)

        # Check if the user specified a suffix to validate
        expected_suffix = None
        for suffix in _SUFFIXES:
            if street_part.upper().endswith(suffix):
                expected_suffix = _CANONICAL_SUFFIXES.get(suffix.strip())
                break

        if swis_options is None:
            swis_options = []
            for code, name in self.swis_map.items():
                if name.upper() in raw_input:
                    swis_options.append(code)

            # Avoid autocomplete fan-out across every Dutchess municipality while
            # the user is still typing, unless the street part is long enough
            # (at least 4 chars) to search in parallel across all towns.
            if not swis_options:
                if len(street_part) < 4:
                    return []
                swis_options = list(self.swis_map.keys())

        suggestions = []
        seen = set()

        import concurrent.futures

        def query_town(swis):
            town_suggestions = []
            for street in street_options:
                attempts = [{'number': number, 'street': street.strip(), 'predir': predir, 'swis': swis}]
                if predir:
                    attempts.append({'number': number, 'street': street.strip(), 'swis': swis})
                for params in attempts:
                    try:
                        resp = self.session.get(
                            f"{API_BASE_URL}/search_extract_addresses.asp",
                            params=params,
                            headers=self.headers,
                            timeout=3,
                        )
                        resp.raise_for_status()
                        payload = resp.json()
                        rows = payload.get('data', []) if payload.get('success') else []
                    except Exception:
                        rows = []

                    for row in rows:
                        parcelgrid = row.get('parcelgrid') or row.get('id')
                        if not parcelgrid:
                            continue
                        
                        # Suffix verification
                        res_suff_raw = (row.get('Loc_mail_st_suff') or row.get('loc_mail_st_suff') or '').strip().upper()
                        res_suff = _CANONICAL_SUFFIXES.get(res_suff_raw, res_suff_raw)
                        if expected_suffix and res_suff and res_suff != expected_suffix:
                            continue

                        addr = self._format_search_address(row)
                        town = (_get_f(row, 'loc_muni_name') or _get_f(row, 'muni_name') or self.swis_map.get(str(_get_f(row, 'swis')), "")).title()
                        zipc = str(_get_f(row, 'loc_zip') or _get_f(row, 'zip') or "").strip()[:5]
                        town_suggestions.append({
                            "address": addr,
                            "town": town,
                            "county": "Dutchess",
                            "zip": zipc,
                            "parcelgrid": parcelgrid,
                            "sbl": parcelgrid,
                            "swis": str(_get_f(row, 'swis') or parcelgrid[:6]),
                        })
                    if town_suggestions:
                        break  # Found match for this street option, stop trying other options for this town
            return town_suggestions

        if len(swis_options) > 1:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(swis_options), 20)) as executor:
                futures = [executor.submit(query_town, swis) for swis in swis_options]
                for future in concurrent.futures.as_completed(futures):
                    for item in future.result():
                        pg = item['parcelgrid']
                        if pg not in seen:
                            seen.add(pg)
                            suggestions.append(item)
                            if len(suggestions) >= limit:
                                return suggestions
        else:
            for swis in swis_options:
                for item in query_town(swis):
                    pg = item['parcelgrid']
                    if pg not in seen:
                        seen.add(pg)
                        suggestions.append(item)
                        if len(suggestions) >= limit:
                            return suggestions

        return suggestions

    def _format_search_address(self, row: dict) -> str:
        fallback = _get_f(row, 'address') or _get_f(row, 'full_address') or _get_f(row, 'label')
        nbr = str(_get_f(row, 'loc_st_nbr', '')).strip()
        pre = str(_get_f(row, 'loc_st_dir', '') or _get_f(row, 'Loc_st_dir', '')).strip()
        name = str(_get_f(row, 'loc_st_name', '')).strip()
        suff = str(_get_f(row, 'loc_mail_st_suff', '') or _get_f(row, 'Loc_mail_st_suff', '')).strip()
        parts = [p for p in [nbr, pre, name, suff] if p]
        return (" ".join(parts) or str(fallback or "")).title()

    @retry(
        stop=stop_after_attempt(3), 
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(CountyAPIError)
    )
    def get_full_rps_data(self, identifier: str) -> dict:
        """Retrieves full RPS data, including physical details from secondary endpoint."""
        try:
            # 1. Get Parcel Summary & Assessment
            resp = self.session.post(f"{API_BASE_URL}/search_extract_parcelgrids.asp", data={'parcelgrid': identifier}, headers=self.headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            rps_list = data.get('data', [])
            if not rps_list: return None
            
            primary = rps_list[0]
            
            # 2. Get Physical Details (Secondary API Call)
            # This endpoint provides sfla, bedrooms, year built, etc.
            params = {
                'parcelid': primary.get('parcel_id'),
                'county': primary.get('swis', '')[:2],
                'town': primary.get('swis', '')[2:4],
                'village': primary.get('swis', '')[4:6]
            }
            details_resp = self.session.get(f"{API_BASE_URL}/get_property_details.asp", params=params, headers=self.headers, timeout=10)
            details_resp.raise_for_status()
            details = details_resp.json().get('data', {})
            
            # Extract first residential building record if available
            res_bldg = details.get('resbldg', [{}])[0] if details.get('resbldg') else {}
            
            # Helper for robust field mapping
            def get_f(source, key, default=0):
                return source.get(key, source.get(key.lower(), source.get(key.upper(), default)))

            # Assemble address
            nbr = str(get_f(primary, 'loc_st_nbr', '')).strip()
            pre = str(get_f(primary, 'Loc_st_dir', '')).strip()
            name = str(get_f(primary, 'loc_st_name', '')).strip()
            suff = str(get_f(primary, 'Loc_mail_st_suff', '')).strip()
            
            addr_parts = [nbr]
            if pre: addr_parts.append(pre)
            addr_parts.append(name)
            if suff: addr_parts.append(suff)
            
            total_av = float(get_f(primary, 'total_av', 0))
            
            return {
                'address': " ".join(addr_parts).title(),
                'sbl': identifier,
                'sqft': float(get_f(res_bldg, 'sfla', get_f(primary, 'sqft', 0))),
                'acreage': float(get_f(primary, 'acreage', 0)),
                'bedrooms': int(get_f(res_bldg, 'nbr_bedrooms', 0)),
                'bathrooms': float(get_f(res_bldg, 'nbr_full_baths', 0)) + (0.5 * float(get_f(res_bldg, 'nbr_half_baths', 0))),
                'year_built': int(get_f(res_bldg, 'yr_built', 0)),
                'assessment_2026': total_av,
                'assessment_2025': 0.0, 
                'property_class': str(get_f(primary, 'prop_class_desc', '')).strip(),
                'condition_code': str(get_f(res_bldg, 'cond_desc', '')).strip(),
                'grade': str(get_f(res_bldg, 'grade_desc', '')).strip(),
                'basement_type': str(get_f(res_bldg, 'rbsmnt_typ_desc', '')).strip(),
                'heat_type': str(get_f(res_bldg, 'heat_type_desc', '')).strip(),
                'style': str(get_f(res_bldg, 'bldg_style_desc', '')).strip()
            }
        except Exception as e:
            import traceback
            traceback.print_exc()
            raise CountyAPIError(f"Failed to retrieve Dutchess RPS data for {identifier}: {e}")

    def get_town_from_identifier(self, identifier: str) -> str:
        swis_prefix = identifier[:6]
        return self.swis_map.get(swis_prefix, "Rhinebeck")
