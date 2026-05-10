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

    def discover_comps_live(self, subject):
        """
        Performs a live discovery of comps using RapidAPI, 
        then enriches them using the official County API.
        Yields progress updates for the UI.
        """
        import subprocess
        import json
        import time
        
        yield {"status": "searching", "message": f"Searching market sales for {subject['address']}..."}
        
        location = "Rhinebeck, NY"
        beds_min = subject['bedrooms'] - 1
        beds_max = subject['bedrooms'] + 1
        
        try:
            cmd = ["bash", "tools/fetch_comps.sh", location, str(int(beds_min)), str(int(beds_max))]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            raw_data = json.loads(result.stdout)
            raw_comps = raw_data.get('data', [])
            
            yield {"status": "found", "count": len(raw_comps), "message": f"Found {len(raw_comps)} potential market comps. Starting verification..."}
            
            enriched_comps = []
            for i, rc in enumerate(raw_comps[:10]): # Process up to 10
                addr_str = rc.get('address', '')
                if not addr_str: continue
                
                yield {"status": "verifying", "address": addr_str, "current": i+1, "total": len(raw_comps[:10]), "message": f"Verifying {addr_str}..."}
                
                # 2-second pause between requests as requested
                time.sleep(2)
                
                parts = addr_str.split(' ')
                num = parts[0]
                street = parts[1]
                
                official_p = None
                retry_count = 0
                while retry_count < 2:
                    official_p = self.search_address(num, street)
                    
                    # Detection logic for rate limiting (empty response on a known valid search)
                    # For this tool, we assume 'None' or empty after we just hit home page might be a block
                    if official_p:
                        break
                    else:
                        yield {"status": "rate_limited", "message": "Rate limit detected! Pausing for 30 seconds...", "wait": 30}
                        time.sleep(30)
                        retry_count += 1
                        # Re-init session to be safe
                        self.session = requests.Session()
                        self.session.get("https://gis.dutchessny.gov/parcelaccess/")
                
                if official_p:
                    official_data = self.get_full_rps_data(official_p['parcelgrid'])
                    if official_data:
                        comp_obj = {
                            'address': official_data['address'],
                            'sbl': official_data['sbl'],
                            'sale_price': float(rc.get('price', 0)) if rc.get('price') else 0,
                            'sale_date': rc.get('last_sold_date', '2025-01-01'),
                            'sqft': official_data['sqft'],
                            'acreage': official_data['acreage'],
                            'bedrooms': official_data['bedrooms'],
                            'bathrooms': official_data['bathrooms'],
                            'year_built': official_data['year_built']
                        }
                        enriched_comps.append(comp_obj)
                        yield {"status": "verified", "comp": comp_obj}
            
            yield {"status": "complete", "comps": enriched_comps}
            
        except Exception as e:
            yield {"status": "error", "message": f"Discovery Error: {str(e)}"}

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

    def ensure_property(self, subject_data):
        """Saves or updates subject property and returns its DB ID."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO properties 
            (address, sbl, sqft, acreage, bedrooms, bathrooms, year_built, assessment_2025)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            subject_data['address'], subject_data['sbl'], subject_data['sqft'], subject_data['acreage'],
            subject_data['bedrooms'], subject_data['bathrooms'], subject_data['year_built'], subject_data['assessment_2025']
        ))
        cursor.execute("SELECT id FROM properties WHERE sbl = ?", (subject_data['sbl'],))
        prop_id = cursor.fetchone()[0]
        conn.commit()
        conn.close()
        return prop_id

    def add_manual_comp(self, property_id, comp_address, sale_price):
        """Searches, enriches, and saves a manual comp to the database."""
        # 1. Parse address
        parts = comp_address.strip().split(' ', 1)
        if len(parts) < 2: return False
        
        num, street = parts
        official_p = self.search_address(num, street)
        
        if not official_p: return False
        
        # 2. Enrich
        official_data = self.get_full_rps_data(official_p['parcelgrid'])
        if not official_data: return False
        
        # 3. Save
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO sales_comps 
            (address, sbl, sale_price, sale_date, sqft, acreage, bedrooms, bathrooms, year_built, target_property_id, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'MANUAL')
        """, (
            official_data['address'], official_data['sbl'], float(sale_price), '2025-01-01',
            official_data['sqft'], official_data['acreage'], official_data['bedrooms'], official_data['bathrooms'], 
            official_data['year_built'], property_id
        ))
        conn.commit()
        conn.close()
        return True
