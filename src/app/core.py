import sqlite3
import time
import os
import subprocess
import json
import re
from app.counties.factory import CountyFactory
from app.exceptions import CountyAPIError

class TaxGrieveCore:
    def __init__(self, db_path='grievance_data.db'):
        self.db_path = db_path

    def get_subject_profile(self, address_string):
        """Identifies property via County, then enriches with RapidAPI."""
        # 1. Get appropriate County Handler
        county = CountyFactory.get_county_handler(address_string)
        
        # 2. Search County First (Authoritative for ID)
        official_p = county.search_address(address_string)
        if not official_p: return None
        
        # Identifier is 'parcelgrid' in Dutchess, might be different in other counties
        # Standardizing on 'identifier' or similar. 
        # For now, Dutchess handler returns a dict with 'parcelgrid'.
        identifier = official_p.get('parcelgrid')
        profile = county.get_full_rps_data(identifier)
        if not profile: return None

        # 3. If building data is missing, recover via RapidAPI
        if profile.get('sqft', 0) == 0 or profile.get('bedrooms', 0) == 0:
            try:
                town = county.get_town_from_identifier(identifier)
                cmd = ["bash", "tools/fetch_comps.sh", f"{profile['address']}, {town}, NY", "0", "99"]
                result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                market_data = json.loads(result.stdout).get('data', [])
                if market_data:
                    md = market_data[0]
                    rf = md.get('resoFacts', {})
                    profile['sqft'] = md.get('livingArea', md.get('area', profile.get('sqft', 0)))
                    profile['bedrooms'] = md.get('bedrooms', md.get('beds', profile.get('bedrooms', 0)))
                    profile['bathrooms'] = md.get('bathrooms', md.get('baths', profile.get('bathrooms', 0)))
                    profile['year_built'] = md.get('yearBuilt', md.get('year_built', profile.get('year_built', 0)))
                    if profile.get('assessment_2025', 0) == 0:
                        profile['assessment_2025'] = rf.get('taxAssessedValue', md.get('taxAssessedValue', 0))
            except: pass
            
        return profile

    def ensure_property(self, subject_data):
        """Ensures the subject property exists in the local SQLite cache."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 1. ALWAYS ensure table exists first
        cursor.execute('''CREATE TABLE IF NOT EXISTS properties 
                        (id INTEGER PRIMARY KEY, address TEXT, sbl TEXT, sqft REAL, acreage REAL, 
                         bedrooms REAL, bathrooms REAL, year_built INTEGER, assessment_2025 REAL, assessment_2026 REAL)''')

        # 2. Then check for schema evolution (migration)
        cursor.execute("PRAGMA table_info(properties)")
        cols = [c[1] for c in cursor.fetchall()]
        if 'assessment_2025' not in cols:
            cursor.execute("ALTER TABLE properties ADD COLUMN assessment_2025 REAL")
        if 'assessment_2026' not in cols:
            cursor.execute("ALTER TABLE properties ADD COLUMN assessment_2026 REAL")
        
        cursor.execute("SELECT id FROM properties WHERE sbl = ?", (subject_data['sbl'],))
        row = cursor.fetchone()
        if not row:
            cursor.execute('''INSERT INTO properties (address, sbl, sqft, acreage, bedrooms, bathrooms, year_built, assessment_2025, assessment_2026) 
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', 
                        (subject_data['address'], subject_data['sbl'], subject_data['sqft'], subject_data['acreage'], 
                         subject_data['bedrooms'], subject_data['bathrooms'], subject_data['year_built'], 
                         subject_data.get('assessment_2025', 0), subject_data.get('assessment_2026', 0)))
            row_id = cursor.lastrowid
        else:
            row_id = row[0]
            # Update values if they changed or were previously zero/missing
            cursor.execute('''UPDATE properties SET 
                                sqft = MAX(sqft, ?),
                                bedrooms = MAX(bedrooms, ?),
                                bathrooms = MAX(bathrooms, ?),
                                year_built = MAX(year_built, ?),
                                assessment_2025 = ?, 
                                assessment_2026 = ? 
                              WHERE id = ?''',
                           (subject_data.get('sqft', 0), subject_data.get('bedrooms', 0), 
                            subject_data.get('bathrooms', 0), subject_data.get('year_built', 0),
                            subject_data.get('assessment_2025', 0), subject_data.get('assessment_2026', 0), row_id))
            
        conn.commit()
        conn.close()
        return row_id

    def discover_comps_live(self, subject, subject_id):
        """Streams comps from RapidAPI, verifies them, and persists to DB immediately."""
        if not os.getenv("RAPIDAPI_KEY"):
             yield {"status": "error", "message": "RAPIDAPI_KEY not found in environment."}
             return

        # Ensure sales_comps schema is up to date
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS sales_comps 
                        (id INTEGER PRIMARY KEY, target_property_id INTEGER, address TEXT, sbl TEXT, 
                         sale_price REAL, sale_date TEXT, sqft REAL, acreage REAL, bedrooms REAL, 
                         bathrooms REAL, year_built INTEGER, zpid TEXT, status TEXT DEFAULT 'VERIFIED',
                         similarity_score REAL, is_outlier INTEGER DEFAULT 0, 
                         assessment_2026 REAL, assessment_2025 REAL)''')
        cursor.execute("PRAGMA table_info(sales_comps)")
        cols = [c[1] for c in cursor.fetchall()]
        if 'zpid' not in cols: cursor.execute("ALTER TABLE sales_comps ADD COLUMN zpid TEXT")
        if 'status' not in cols: cursor.execute("ALTER TABLE sales_comps ADD COLUMN status TEXT DEFAULT 'VERIFIED'")
        if 'assessment_2026' not in cols: cursor.execute("ALTER TABLE sales_comps ADD COLUMN assessment_2026 REAL")
        if 'assessment_2025' not in cols: cursor.execute("ALTER TABLE sales_comps ADD COLUMN assessment_2025 REAL")
        conn.commit()

        yield {"status": "searching", "message": f"Searching market sales for {subject['address']}..."}
        
        county = CountyFactory.get_county_handler(subject['address'])
        town = county.get_town_from_identifier(subject['sbl'])
        location = f"{town}, NY"
        
        beds_min = max(1, int(subject.get('bedrooms', 3)) - 1)
        beds_max = int(subject.get('bedrooms', 3)) + 1
        
        if subject.get('bedrooms', 0) == 0:
            beds_min, beds_max = 1, 99
            yield {"status": "searching", "message": "Subject building data missing. Performing broad market search..."}

        yield {"status": "searching", "message": f"Querying RapidAPI for sold listings in {location} ({beds_min}-{beds_max} beds)..."}
        
        try:
            cmd = ["bash", "tools/fetch_comps.sh", location, str(beds_min), str(beds_max), "RECENTLY_SOLD"]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=30)
            
            try:
                response_data = json.loads(result.stdout)
            except json.JSONDecodeError:
                yield {"status": "error", "message": "Failed to parse RapidAPI response."}
                return

            raw_comps = response_data.get('data', [])
            
            if not raw_comps:
                yield {"status": "searching", "message": "No specific matches. Trying broader search..."}
                cmd = ["bash", "tools/fetch_comps.sh", location, "0", "99", "RECENTLY_SOLD"]
                result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=30)
                raw_comps = json.loads(result.stdout).get('data', [])

            yield {"status": "found", "count": len(raw_comps), "message": f"Found {len(raw_comps)} listings. Resuming/Filtering..."}
            
            enriched_comps = []
            for i, rc in enumerate(raw_comps[:40]):
                zpid = str(rc.get('zpid', rc.get('id', '')))
                
                # Check if already processed
                cursor.execute("SELECT status, address, assessment_2026 FROM sales_comps WHERE target_property_id = ? AND zpid = ?", (subject_id, zpid))
                existing = cursor.fetchone()
                if existing:
                    # REPAIR LOGIC: If existing record is missing assessment data, force a re-verify
                    if existing[0] != 'REJECTED' and (existing[2] is None or existing[2] == 0):
                        yield {"status": "info", "message": f"Repairing missing data for: {existing[1]}"}
                        # Proceed to verification logic below instead of continuing
                    elif existing[0] != 'REJECTED':
                        # Fetch full existing data to return to live stream
                        cursor.execute("SELECT * FROM sales_comps WHERE target_property_id = ? AND zpid = ?", (subject_id, zpid))
                        row = cursor.fetchone()
                        row_cols = [description[0] for description in cursor.description]
                        comp_obj = dict(zip(row_cols, row))
                        enriched_comps.append(comp_obj)
                        yield {"status": "verified", "comp": comp_obj, "message": f"Resumed: {comp_obj['address']}"}
                        continue
                    else:
                        yield {"status": "resuming", "message": f"Skipping rejected: {existing[1]}"}
                        continue

                status_market = rc.get('homeStatus', rc.get('status', '')).upper()
                if 'FOR_SALE' in status_market: continue

                full_addr = rc.get('streetAddress', rc.get('address', ''))
                if not full_addr: continue
                
                comp_identifier = rc.get('parcelNumber', rc.get('resoFacts', {}).get('parcelNumber'))
                official_data = None
                
                yield {"status": "verifying", "address": full_addr, "current": i+1, "total": min(len(raw_comps), 40), "message": f"Verifying {full_addr}..."}

                if comp_identifier:
                    official_data = county.get_full_rps_data(comp_identifier)
                
                if not official_data:
                    # Pass subject's SWIS as preferred to keep verification fast
                    subj_swis = subject.get('sbl', '      ')[:6]
                    official_p = county.search_address(full_addr, preferred_swis=subj_swis)
                    if official_p: 
                        official_data = county.get_full_rps_data(official_p.get('parcelgrid'))
                        if official_data:
                             yield {"status": "info", "message": f"MATCH: Found {full_addr} in official records."}

                sqft = rc.get('livingArea', rc.get('area', 0))
                acreage = rc.get('lotAreaValue', 0)
                if rc.get('lotAreaUnit') == 'sqft': acreage = round(acreage / 43560, 2)
                sale_price = float(rc.get('price', 0)) if rc.get('price') else 0

                comp_obj = None
                if official_data and sale_price > 0:
                    comp_obj = {
                        'address': official_data['address'], 'sbl': official_data['sbl'],
                        'sale_price': sale_price,
                        'sale_date': rc.get('last_sold_date', '2025-01-01'),
                        'sqft': sqft or official_data['sqft'], 'acreage': acreage or official_data['acreage'],
                        'bedrooms': rc.get('bedrooms', official_data['bedrooms']),
                        'bathrooms': rc.get('bathrooms', official_data['bathrooms']),
                        'year_built': rc.get('year_built', official_data['year_built']),
                        'assessment_2026': official_data.get('assessment_2026', 0),
                        'zpid': zpid, 'status': 'VERIFIED'
                    }
                elif sale_price > 0 and sqft > 0:
                    comp_obj = {
                        'address': full_addr, 'sbl': 'UNVERIFIED',
                        'sale_price': sale_price, 'sale_date': rc.get('last_sold_date', '2025-01-01'),
                        'sqft': sqft, 'acreage': acreage,
                        'bedrooms': rc.get('bedrooms', 0), 'bathrooms': rc.get('bathrooms', 0),
                        'year_built': rc.get('year_built', 0),
                        'assessment_2026': 0,
                        'zpid': zpid, 'status': 'UNVERIFIED'
                    }

                if comp_obj:
                    # Use INSERT OR REPLACE to update existing incomplete records during 'repair'
                    cursor.execute("""
                        INSERT OR REPLACE INTO sales_comps (target_property_id, address, sbl, sale_price, sale_date, sqft, acreage, bedrooms, bathrooms, year_built, zpid, status, assessment_2026)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (subject_id, comp_obj['address'], comp_obj['sbl'], comp_obj['sale_price'], comp_obj['sale_date'], 
                         comp_obj['sqft'], comp_obj['acreage'], comp_obj['bedrooms'], comp_obj['bathrooms'], comp_obj['year_built'], 
                         comp_obj['zpid'], comp_obj['status'], comp_obj.get('assessment_2026', 0)))
                    conn.commit()
                    enriched_comps.append(comp_obj)
                    yield {"status": "verified", "comp": comp_obj}
            
            yield {"status": "complete", "comps": enriched_comps}
        except Exception as e:
            import traceback
            traceback.print_exc()
            yield {"status": "error", "message": f"Discovery Error: {str(e)}"}
        finally:
            conn.close()

    def calculate_effective_year_built(self, original_year, renovation_year):
        """
        Calculates a weighted Effective Year Built based on a major renovation.
        Heuristic: Split the difference between original and renovation.
        """
        if not renovation_year or renovation_year <= original_year:
            return original_year
        return int((original_year + renovation_year) / 2)

    def calculate_similarity(self, subject, comp, renovation_year=None):
        """Similarity scoring (40% Sqft, 30% Age, 20% Acreage, 10% Distance)"""
        def normalize(val, target, tolerance):
            if target == 0: return 0
            return max(0, 1 - (abs(val - target) / (target * tolerance)))
        
        sqft_score = normalize(comp.get('sqft', 0), subject.get('sqft', 0), 0.20) * 40
        
        # Use effective year built if renovation_year provided
        subj_year = subject.get('year_built', 0)
        if renovation_year:
            subj_year = self.calculate_effective_year_built(subj_year, renovation_year)
            
        age_score = max(0, 1 - (abs(comp.get('year_built', 0) - subj_year) / 50)) * 30
        acre_score = normalize(comp.get('acreage', 0), subject.get('acreage', 0), 0.50) * 20
        dist = comp.get('distance_miles', 0.5)
        if dist is None: dist = 0.5
        dist_score = max(0, 1 - (dist / 5)) * 10
        
        return round(sqft_score + age_score + acre_score + dist_score, 1)

    def calculate_valuation(self, subject, comps, adjs=None, renovation_year=None):
        """Appraisal math with outlier detection (25% variance limit)."""
        if adjs is None: 
            adjs = {'sqft': 150.0, 'bathroom': 15000.0, 'acre': 50000.0, 'bedroom': 10000.0, 'year_built': 1000.0}
        
        def get_val(obj, key, default=0):
            val = obj.get(key)
            return val if val is not None else default
        
        # Sanity Check: If subject data is missing, we cannot calculate accurately
        if get_val(subject, 'sqft') == 0:
            return 0, []

        subj_year = get_val(subject, 'year_built')
        if renovation_year:
            subj_year = self.calculate_effective_year_built(subj_year, renovation_year)
            
        raw_results = []
        for comp in comps:
            # Skip rejected comps in valuation
            if comp.get('status') == 'REJECTED':
                continue

            adj_price = get_val(comp, 'sale_price', 0)
            if adj_price == 0: continue # Cannot use as comp without price

            gla_adj = (get_val(subject, 'sqft') - get_val(comp, 'sqft')) * adjs['sqft']
            acre_adj = (get_val(subject, 'acreage') - get_val(comp, 'acreage')) * adjs['acre']
            bath_adj = (get_val(subject, 'bathrooms') - get_val(comp, 'bathrooms')) * adjs['bathroom']
            bed_adj = (get_val(subject, 'bedrooms') - get_val(comp, 'bedrooms')) * adjs['bedroom']
            age_adj = (subj_year - get_val(comp, 'year_built')) * adjs['year_built']
            
            reconciled = adj_price + gla_adj + acre_adj + bath_adj + bed_adj + age_adj
            
            # Safety Floor: Reconciled value cannot be less than 10% of sale price
            reconciled = max(reconciled, adj_price * 0.1)

            score = self.calculate_similarity(subject, comp, renovation_year=renovation_year)
            
            raw_results.append({
                'address': comp['address'], 'sale_price': comp['sale_price'],
                'reconciled_value': reconciled, 'similarity_score': score,
                'adjustments': {'gla': gla_adj, 'acreage': acre_adj, 'bath': bath_adj, 'age': age_adj},
                'zpid': comp.get('zpid'),
                'status': comp.get('status', 'VERIFIED'),
                'assessment_2026': comp.get('assessment_2026', 0),
                'assessment_2025': comp.get('assessment_2025', 0),
                'sqft': comp.get('sqft', 0),
                'year_built': comp.get('year_built', 0),
                'bedrooms': comp.get('bedrooms', 0),
                'bathrooms': comp.get('bathrooms', 0),
                'acreage': comp.get('acreage', 0)
            })
            
        if not raw_results: return 0, []
        
        mean_val = sum(r['reconciled_value'] for r in raw_results) / len(raw_results)
        valid_results = [r for r in raw_results if abs(r['reconciled_value'] - mean_val) / mean_val <= 0.25]
        
        for r in raw_results: 
            r['is_outlier'] = r not in valid_results
            
        final_val = sum(v['reconciled_value'] for v in valid_results) / len(valid_results) if valid_results else mean_val
        return final_val, raw_results

    def add_manual_comp(self, property_id, address, price):
        """Verifies and adds a manual comp to the database."""
        county = CountyFactory.get_county_handler(address)
        official_p = county.search_address(address)
        if not official_p: return False
        
        data = county.get_full_rps_data(official_p.get('parcelgrid'))
        if not data: return False
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS sales_comps 
                        (id INTEGER PRIMARY KEY, target_property_id INTEGER, address TEXT, sbl TEXT, 
                         sale_price REAL, sale_date TEXT, sqft REAL, acreage REAL, bedrooms REAL, 
                         bathrooms REAL, year_built INTEGER, zpid TEXT, status TEXT DEFAULT 'VERIFIED')''')
        cursor.execute('''INSERT INTO sales_comps (target_property_id, address, sbl, sale_price, sale_date, sqft, acreage, bedrooms, bathrooms, year_built, status, assessment_2026) 
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'MANUAL', ?)''',
                    (property_id, data['address'], data['sbl'], price, '2025-01-01', data['sqft'], data['acreage'], 
                     data['bedrooms'], data['bathrooms'], data['year_built'], data.get('assessment_2026', 0)))
        conn.commit()
        conn.close()
        return True
