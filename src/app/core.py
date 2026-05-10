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
        """Combines search and details into one profile (Simplified due to API restrictions)."""
        resp = self.session.post(f"{API_BASE_URL}/search_extract_parcelgrids.asp", data={'parcelgrid': parcelgrid}, headers=self.headers)
        rps_list = resp.json().get('data', [])
        if not rps_list: return None
        primary = rps_list[0]
        
        # Note: resbldg data is no longer available via get_property_details.asp
        # We will use what's available in the primary record and fallback for the rest.
        return {
            'address': f"{primary['loc_st_nbr'].strip()} {primary['loc_st_name'].strip()} {primary['Loc_mail_st_suff'].strip()}".title(),
            'sbl': parcelgrid,
            'sqft': primary.get('sfla', primary.get('sqft', 0)), # Try multiple keys
            'acreage': primary.get('acreage', 0),
            'bedrooms': primary.get('nbr_bedrooms', 0),
            'bathrooms': float(primary.get('nbr_full_baths', 0)) + (0.5 * float(primary.get('nbr_half_baths', 0))),
            'year_built': primary.get('yr_built', 0),
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
                            'sqft': rc.get('sqft') or official_data['sqft'],
                            'acreage': rc.get('lot_size', 0) or official_data['acreage'],
                            'bedrooms': rc.get('beds') or official_data['bedrooms'],
                            'bathrooms': rc.get('baths') or official_data['bathrooms'],
                            'year_built': rc.get('year_built') or official_data['year_built']
                        }
                        enriched_comps.append(comp_obj)
                        yield {"status": "verified", "comp": comp_obj}
                else:
                    # If County verification fails, still use RapidAPI data but mark as unverified
                    comp_obj = {
                        'address': addr_str,
                        'sbl': 'UNVERIFIED',
                        'sale_price': float(rc.get('price', 0)) if rc.get('price') else 0,
                        'sale_date': rc.get('last_sold_date', '2025-01-01'),
                        'sqft': rc.get('sqft', 0),
                        'acreage': rc.get('lot_size', 0),
                        'bedrooms': rc.get('beds', 0),
                        'bathrooms': rc.get('baths', 0),
                        'year_built': rc.get('year_built', 0)
                    }
                    if comp_obj['sqft'] > 0: # Only add if we have basic data
                        enriched_comps.append(comp_obj)
                        yield {"status": "verified", "comp": comp_obj}
            
            yield {"status": "complete", "comps": enriched_comps}
            
        except Exception as e:
            yield {"status": "error", "message": f"Discovery Error: {str(e)}"}

    def calculate_similarity(self, subject, comp):
        """
        Calculates a similarity score (0-100) between subject and comp.
        Weights: Sqft (40%), Year Built (30%), Acreage (20%), Distance (10%).
        """
        def normalize(val, target, tolerance):
            if target == 0: return 0
            diff = abs(val - target)
            return max(0, 1 - (diff / (target * tolerance)))

        # 1. SQFT (40%) - 20% tolerance
        sqft_score = normalize(comp.get('sqft', 0), subject.get('sqft', 0), 0.20) * 40
        
        # 2. Year Built (30%) - 50 year tolerance
        age_diff = abs(comp.get('year_built', 0) - subject.get('year_built', 0))
        age_score = max(0, 1 - (age_diff / 50)) * 30
        
        # 3. Acreage (20%) - 50% tolerance
        acre_score = normalize(comp.get('acreage', 0), subject.get('acreage', 0), 0.50) * 20
        
        # 4. Distance (10%) - 5 mile tolerance
        dist = comp.get('distance_miles')
        if dist is None: dist = 0.5 # Default to 0.5 miles if unknown
        dist_score = max(0, 1 - (dist / 5)) * 10
        
        total_score = sqft_score + age_score + acre_score + dist_score
        return round(total_score, 1)

    def calculate_valuation(self, subject, comps, adjs=None):
        """Performs appraisal math with outlier detection."""
        if adjs is None:
            adjs = {'sqft': 150.0, 'bathroom': 15000.0, 'acre': 50000.0, 'bedroom': 10000.0, 'year_built': 1000.0}
        
        def get_val(obj, key, default=0):
            val = obj.get(key)
            return val if val is not None else default

        raw_results = []
        for comp in comps:
            adj_price = comp['sale_price']
            
            gla_adj = (get_val(subject, 'sqft') - get_val(comp, 'sqft')) * adjs['sqft']
            acre_adj = (get_val(subject, 'acreage') - get_val(comp, 'acreage')) * adjs['acre']
            bath_adj = (get_val(subject, 'bathrooms') - get_val(comp, 'bathrooms')) * adjs['bathroom']
            bed_adj = (get_val(subject, 'bedrooms') - get_val(comp, 'bedrooms')) * adjs['bedroom']
            age_adj = (get_val(subject, 'year_built') - get_val(comp, 'year_built')) * adjs['year_built']
            
            total_adj = gla_adj + acre_adj + bath_adj + bed_adj + age_adj
            reconciled = adj_price + total_adj
            
            # Calculate Similarity for UI display
            score = self.calculate_similarity(subject, comp)
            
            raw_results.append({
                'address': comp['address'],
                'sale_price': comp['sale_price'],
                'reconciled_value': reconciled,
                'similarity_score': score,
                'adjustments': {
                    'gla': gla_adj,
                    'acreage': acre_adj,
                    'bath': bath_adj,
                    'age': age_adj
                }
            })
            
        if not raw_results: return 0, []

        # Outlier Detection (25% threshold)
        mean_val = sum(r['reconciled_value'] for r in raw_results) / len(raw_results)
        valid_results = []
        for r in raw_results:
            deviation = abs(r['reconciled_value'] - mean_val) / mean_val
            r['is_outlier'] = deviation > 0.25
            if not r['is_outlier']:
                valid_results.append(r['reconciled_value'])
        
        market_value = sum(valid_results) / len(valid_results) if valid_results else mean_val
        return market_value, raw_results

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
