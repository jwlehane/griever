import requests
import sqlite3
import time
import os

API_BASE_URL = "https://gis.dutchessny.gov/parcelaccess/asp"

class TaxGrieveCore:
    def __init__(self, db_path='grievance_data.db'):
        self.db_path = db_path
        self.session = requests.Session()
        self.session.get("https://gis.dutchessny.gov/parcelaccess/")
        self.headers = {
            "Referer": "https://gis.dutchessny.gov/parcelaccess/",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

    def search_address(self, number, street_full, swis=""):
        """Finds parcel info for an address with robust parsing."""
        # Standardize input
        raw = street_full.upper().strip()
        
        # Replace full words with single-letter prefixes
        if raw.startswith("NORTH "): raw = raw.replace("NORTH ", "N ", 1)
        elif raw.startswith("SOUTH "): raw = raw.replace("SOUTH ", "S ", 1)
        elif raw.startswith("EAST "): raw = raw.replace("EAST ", "E ", 1)
        elif raw.startswith("WEST "): raw = raw.replace("WEST ", "W ", 1)

        # Common suffix stripping (Dutchess API preferred)
        suffixes = [" STREET", " ST", " ROAD", " RD", " AVENUE", " AVE", " DRIVE", " DR", " LANE", " LN", " COURT", " CT", " PLACE", " PL"]
        clean_street = raw
        for s in suffixes:
            if clean_street.endswith(s):
                clean_street = clean_street[:len(clean_street)-len(s)]
                break

        predir = ""
        # Now extract prefix and base street name
        if clean_street.startswith("N "):
            predir = "N"
            street = clean_street[2:]
        elif clean_street.startswith("S "):
            predir = "S"
            street = clean_street[2:]
        elif clean_street.startswith("E "):
            predir = "E"
            street = clean_street[2:]
        elif clean_street.startswith("W "):
            predir = "W"
            street = clean_street[2:]
        else:
            street = clean_street

        params = {
            'number': str(number),
            'street': street.strip(),
            'predir': predir,
            'swis': swis
        }
        
        # Search across known municipalities
        swis_options = [swis] if swis else ["135001", "135089", "134889", "132400", "133600"]
        
        for s in swis_options:
            params['swis'] = s
            try:
                # Debug log to console
                print(f"DEBUG: API Query -> Num: {params['number']}, Street: {params['street']}, Predir: {params['predir']}, SWIS: {s}")
                resp = self.session.get(f"{API_BASE_URL}/search_extract_addresses.asp", params=params, headers=self.headers, timeout=5)
                data = resp.json()
                if data.get('success') and data.get('data'):
                    return data['data'][0]
            except:
                continue
        return None

    def get_property_details(self, parcel_id, swis):
        """Fetches detailed physical characteristics."""
        params = {
            'parcelid': parcel_id,
            'county': swis[:2],
            'town': swis[2:4],
            'village': swis[4:6]
        }
        resp = self.session.get(f"{API_BASE_URL}/get_property_details.asp", params=params, headers=self.headers)
        return resp.json().get('data', {})

    def get_full_rps_data(self, parcelgrid):
        """Combines search and details into one profile."""
        resp = self.session.post(f"{API_BASE_URL}/search_extract_parcelgrids.asp", data={'parcelgrid': parcelgrid}, headers=self.headers)
        rps_list = resp.json().get('data', [])
        if not rps_list: return None
        primary = rps_list[0]
        
        details = self.get_property_details(primary['parcel_id'], primary['swis'])
        res_bldg = details.get('resbldg', [{}])[0]
        
        return {
            'address': f"{primary['loc_st_nbr'].strip()} {primary['loc_st_name'].strip()} {primary['Loc_mail_st_suff'].strip()}".title(),
            'sbl': parcelgrid,
            'sqft': res_bldg.get('sfla', 0),
            'acreage': primary.get('acreage', 0),
            'bedrooms': res_bldg.get('nbr_bedrooms', 0),
            'bathrooms': res_bldg.get('nbr_full_baths', 0) + (0.5 * res_bldg.get('nbr_half_baths', 0)),
            'year_built': res_bldg.get('yr_built', 0),
            'assessment_2025': primary.get('total_av', 0),
            'property_class': primary.get('prop_class_desc', '').strip()
        }

    def calculate_valuation(self, subject, comps, adjs=None):
        """Performs appraisal math."""
        if adjs is None:
            adjs = {'sqft': 150.0, 'bathroom': 15000.0, 'acre': 50000.0, 'bedroom': 10000.0, 'year_built': 1000.0}
        
        results = []
        for comp in comps:
            adj_price = comp['sale_price']
            
            gla_adj = (subject['sqft'] - comp['sqft']) * adjs['sqft']
            acre_adj = (subject['acreage'] - comp['acreage']) * adjs['acre']
            bath_adj = (subject['bathrooms'] - comp['bathrooms']) * adjs['bathroom']
            bed_adj = (subject['bedrooms'] - comp['bedrooms']) * adjs['bedroom']
            age_adj = (subject['year_built'] - comp['year_built']) * adjs['year_built']
            
            total_adj = gla_adj + acre_adj + bath_adj + bed_adj + age_adj
            reconciled = adj_price + total_adj
            
            results.append({
                'address': comp['address'],
                'sale_price': comp['sale_price'],
                'reconciled_value': reconciled,
                'adjustments': {
                    'gla': gla_adj,
                    'acreage': acre_adj,
                    'bath': bath_adj,
                    'age': age_adj
                }
            })
            
        market_value = sum(r['reconciled_value'] for r in results) / len(results) if results else 0
        return market_value, results
