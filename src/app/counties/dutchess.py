import requests
import re
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from app.counties.base import CountyInterface
from app.exceptions import CountyAPIError
from app.logging_safe import safe_addr

API_BASE_URL = "https://gis.dutchessny.gov/parcelaccess/asp"

class DutchessCounty(CountyInterface):
    def __init__(self):
        self.session = requests.Session()
        # Initialize session to get cookies if necessary
        self.session.get("https://gis.dutchessny.gov/parcelaccess/")
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
        
        clean_street = street_part
        if clean_street.startswith("NORTH "): clean_street = clean_street.replace("NORTH ", "N ", 1)
        elif clean_street.startswith("SOUTH "): clean_street = clean_street.replace("SOUTH ", "S ", 1)
        elif clean_street.startswith("EAST "): clean_street = clean_street.replace("EAST ", "E ", 1)
        elif clean_street.startswith("WEST "): clean_street = clean_street.replace("WEST ", "W ", 1)

        suffixes = [" STREET", " ST", " ROAD", " RD", " AVENUE", " AVE", " DRIVE", " DR", " LANE", " LN", " COURT", " CT", " PLACE", " PL", " TURNPIKE", " TPKE"]
        street_base = clean_street
        has_suffix = False
        for s in suffixes:
            if clean_street.endswith(s):
                street_base = clean_street[:len(clean_street)-len(s)].strip()
                has_suffix = True
                break

        predir = ""
        street_no_dir = street_base
        if street_base.startswith("N "): 
            predir, street_no_dir = "N", street_base[2:]
        elif street_base.startswith("S "): 
            predir, street_no_dir = "S", street_base[2:]
        elif street_base.startswith("E "): 
            predir, street_no_dir = "E", street_base[2:]
        elif street_base.startswith("W "): 
            predir, street_no_dir = "W", street_base[2:]

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

        # Street options should include:
        # 1. The cleaned street (with 'N ', 'ST', etc. potentially still in it)
        # 2. The street base (suffix removed)
        # 3. If a predir was found, the street base WITHOUT the predir
        street_options = [clean_street, street_base]
        if street_no_dir != street_base:
            street_options.append(street_no_dir)
        
        # Deduplicate while preserving order
        seen = set()
        street_options = [x for x in street_options if not (x in seen or seen.add(x))]
        
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
                            if 'parcelgrid' not in res and 'id' in res: res['parcelgrid'] = res['id']
                            print(f"  FOUND in {town_name} (no predir)")
                            return res
                    except:
                        pass
        print(f"  NOT FOUND")
        return None

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
