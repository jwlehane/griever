import sqlite3
import time
import os
import subprocess
import json
import re
import math
from app.counties.factory import CountyFactory
from app.exceptions import CountyAPIError
from app.equalization import get_rate as _er_rate, implied_market_value

class TaxGrieveCore:
    def __init__(self, db_path='grievance_data.db'):
        self.db_path = db_path

    def _geocode(self, address_string):
        """Return (lat, lon, zip) using the US Census Geocoder, or (None, None, None)."""
        try:
            import requests
            r = requests.get(
                "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress",
                params={"address": f"{address_string}, NY", "benchmark": "Public_AR_Current", "format": "json"},
                timeout=5,
            )
            r.raise_for_status()
            matches = r.json().get('result', {}).get('addressMatches', []) or []
            if matches:
                coords = matches[0].get('coordinates', {}) or {}
                comp = matches[0].get('addressComponents', {}) or {}
                return coords.get('y'), coords.get('x'), (comp.get('zip') or '').strip()[:5]
        except Exception:
            pass
        return None, None, None

    def get_subject_profile(self, address_string):
        """Identifies property via County, then enriches with RapidAPI."""
        # 0. Local DB cache check — if we've already resolved this address
        # (recognized by the leading "<number> <street>" prefix), skip the
        # slow upstream API call. Speeds up retries when NYS is sluggish.
        cached = self._lookup_cached_subject(address_string)
        if cached:
            # Backfill lat/lon/zip if we never geocoded this property before
            if not cached.get('latitude') or not cached.get('longitude'):
                lat, lon, z = self._geocode(address_string)
                if lat and lon:
                    try:
                        conn = sqlite3.connect(self.db_path)
                        c = conn.cursor()
                        c.execute("UPDATE properties SET latitude = COALESCE(latitude, ?), longitude = COALESCE(longitude, ?), zip = COALESCE(zip, ?) WHERE id = ?",
                                  (lat, lon, z, cached['id']))
                        conn.commit()
                        conn.close()
                        cached['latitude'] = cached.get('latitude') or lat
                        cached['longitude'] = cached.get('longitude') or lon
                        cached['zip'] = cached.get('zip') or z
                    except sqlite3.Error:
                        pass
            return cached

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

        # 4. Geocode for distance math + ZIP-based scoping later
        lat, lon, zipc = self._geocode(address_string)
        if lat is not None and lon is not None:
            profile['latitude'] = lat
            profile['longitude'] = lon
        if zipc:
            profile['zip'] = zipc

        return profile

    def _lookup_cached_subject(self, address_string):
        """Return a cached subject dict matching the leading "<num> <street>"
        portion of `address_string`, narrowed to the right county when the
        input includes a town hint. None if no usable cache hit."""
        m = re.match(r"^\s*(\d+)\s+([^,]+)", address_string)
        if not m:
            return None
        number = m.group(1)
        street = m.group(2).strip()
        # Build a relaxed LIKE pattern: "60 Orchard%"
        pattern = f"{number} {street}%"

        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("PRAGMA table_info(properties)")
            cols = {row[1] for row in c.fetchall()}
            if 'sbl' not in cols:
                conn.close()
                return None
            c.execute(
                "SELECT * FROM properties WHERE address LIKE ? COLLATE NOCASE AND sbl IS NOT NULL",
                (pattern,),
            )
            rows = [dict(r) for r in c.fetchall()]
            conn.close()
        except sqlite3.Error:
            return None
        if not rows:
            return None

        # If the input mentioned a town, prefer the row whose SBL prefix maps
        # to that town. Otherwise return the first hit.
        lower = address_string.lower()
        for row in rows:
            sbl = row.get('sbl') or ''
            try:
                county = CountyFactory.get_county_handler(address_string=address_string, sbl=sbl)
                town = (county.get_town_from_identifier(sbl) or '').lower()
                if town and town in lower:
                    return row
            except Exception:
                continue
        return rows[0]

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
        if 'latitude' not in cols:
            cursor.execute("ALTER TABLE properties ADD COLUMN latitude REAL")
        if 'longitude' not in cols:
            cursor.execute("ALTER TABLE properties ADD COLUMN longitude REAL")
        if 'zip' not in cols:
            cursor.execute("ALTER TABLE properties ADD COLUMN zip TEXT")
        if 'property_class' not in cols:
            cursor.execute("ALTER TABLE properties ADD COLUMN property_class TEXT")
        
        cursor.execute("SELECT id FROM properties WHERE sbl = ?", (subject_data['sbl'],))
        row = cursor.fetchone()
        if not row:
            cursor.execute('''INSERT INTO properties (address, sbl, sqft, acreage, bedrooms, bathrooms, year_built, assessment_2025, assessment_2026, latitude, longitude, zip, property_class)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                        (subject_data['address'], subject_data['sbl'], subject_data['sqft'], subject_data['acreage'],
                         subject_data['bedrooms'], subject_data['bathrooms'], subject_data['year_built'],
                         subject_data.get('assessment_2025', 0), subject_data.get('assessment_2026', 0),
                         subject_data.get('latitude'), subject_data.get('longitude'), subject_data.get('zip'),
                         subject_data.get('property_class')))
            row_id = cursor.lastrowid
        else:
            row_id = row[0]
            cursor.execute('''UPDATE properties SET
                                sqft = MAX(sqft, ?),
                                bedrooms = MAX(bedrooms, ?),
                                bathrooms = MAX(bathrooms, ?),
                                year_built = MAX(year_built, ?),
                                assessment_2025 = COALESCE(NULLIF(?, 0), assessment_2025),
                                assessment_2026 = COALESCE(NULLIF(?, 0), assessment_2026),
                                latitude = COALESCE(?, latitude),
                                longitude = COALESCE(?, longitude),
                                zip = COALESCE(?, zip),
                                property_class = COALESCE(NULLIF(?, ''), property_class)
                              WHERE id = ?''',
                           (subject_data.get('sqft', 0), subject_data.get('bedrooms', 0),
                            subject_data.get('bathrooms', 0), subject_data.get('year_built', 0),
                            subject_data.get('assessment_2025', 0), subject_data.get('assessment_2026', 0),
                            subject_data.get('latitude'), subject_data.get('longitude'), subject_data.get('zip'),
                            subject_data.get('property_class'),
                            row_id))
            
        conn.commit()
        conn.close()
        return row_id

    def discover_comps_live(self, subject, subject_id):
        """Streams comps from RapidAPI, verifies them, and persists to DB immediately."""
        # Ensure sales_comps schema is up to date BEFORE any early returns so
        # downstream SELECTs (in main.py) don't hit missing columns when the
        # API key is absent.
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
        if 'distance_miles' not in cols: cursor.execute("ALTER TABLE sales_comps ADD COLUMN distance_miles REAL")

        # Drop duplicate (target_property_id, zpid) rows that accumulated before
        # we added the UNIQUE index, keeping the most recent (max id) per pair.
        cursor.execute("""
            DELETE FROM sales_comps WHERE id NOT IN (
                SELECT MAX(id) FROM sales_comps
                WHERE zpid IS NOT NULL AND zpid != ''
                GROUP BY target_property_id, zpid
            ) AND zpid IS NOT NULL AND zpid != ''
        """)
        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_sales_comps_subject_zpid
            ON sales_comps(target_property_id, zpid)
            WHERE zpid IS NOT NULL AND zpid != ''
        """)
        conn.commit()
        conn.close()

        if not os.getenv("RAPIDAPI_KEY"):
             yield {"status": "error", "message": "RAPIDAPI_KEY not found in environment. Add it to .env to enable comp discovery."}
             return

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        yield {"status": "searching", "message": f"Searching market sales for {subject['address']}..."}

        # Route by SBL — the bare street address can be in either county.
        county = CountyFactory.get_county_handler(address_string=subject['address'], sbl=subject.get('sbl'))
        town = county.get_town_from_identifier(subject['sbl'])
        location = f"{town}, NY"

        # For Ulster, the per-comp NYS verification is the slowest path. Swap
        # in a fast-fail variant (3s timeout) so one slow query can't multiply
        # across dozens of comps. Comps that don't verify in time still get
        # captured as UNVERIFIED using the RapidAPI raw fields.
        try:
            from app.counties.ulster import UlsterCounty
            if isinstance(county, UlsterCounty):
                county = UlsterCounty(timeout=4)
        except ImportError:
            pass
        
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

            # Property-class and same-municipality filtering.
            from app.property_class import expected_hometype
            target_hometype = expected_hometype(subject.get('property_class'))
            subject_town_lc = (town or '').lower()

            filtered = []
            dropped_class = 0
            dropped_town = 0
            for rc in raw_comps:
                # Property class match — only when subject class is known
                if target_hometype:
                    ht = (rc.get('homeType') or '').upper()
                    if ht and ht != target_hometype:
                        dropped_class += 1
                        continue
                # Same-municipality scope (city/town must match subject's town)
                if subject_town_lc:
                    comp_city = (rc.get('addressCity') or rc.get('city') or '').lower()
                    if comp_city and comp_city != subject_town_lc:
                        # Allow if the comp address mentions the subject town
                        # (Census/Zillow city can be the postal city, not the
                        # assessing town — keep when no contradiction).
                        if subject_town_lc not in (rc.get('address') or '').lower():
                            dropped_town += 1
                            continue
                filtered.append(rc)

            if dropped_class or dropped_town:
                yield {"status": "info",
                       "message": f"Filtered out {dropped_class} non-matching property classes and {dropped_town} out-of-town comps."}

            raw_comps = filtered
            yield {"status": "found", "count": len(raw_comps), "message": f"Found {len(raw_comps)} listings. Resuming/Filtering..."}

            enriched_comps = []
            # We process ALL raw comps returned by the search (RapidAPI usually limits to 40 anyway)
            total_raw = len(raw_comps)
            for i, rc in enumerate(raw_comps):
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
                
                yield {"status": "verifying", "address": full_addr, "current": i+1, "total": total_raw, "message": f"Verifying {full_addr}..."}

                # Verification policy: only do the cheap path (identifier-based
                # lookup) when the source supplies a parcel number that matches
                # the county's format. Address-based verification is slow at
                # scale (a 5s timeout × 40 comps = 3+ minutes) and the
                # downstream valuation math only needs sqft/beds/baths/year/
                # acreage/price — all already provided by RapidAPI. Comps
                # without a matching identifier flow through as UNVERIFIED.
                try:
                    if comp_identifier:
                        official_data = county.get_full_rps_data(comp_identifier)
                except (CountyAPIError, Exception) as ve:
                    print(f"  verify skipped for {full_addr}: {ve}")
                    official_data = None

                sqft = rc.get('livingArea', rc.get('area', 0))
                acreage = rc.get('lotAreaValue', 0)
                if rc.get('lotAreaUnit') == 'sqft' and acreage:
                    acreage = round(acreage / 43560, 4)
                sale_price = float(rc.get('price', 0)) if rc.get('price') else 0

                # Haversine distance from subject (miles) when both points known.
                comp_lat = rc.get('latitude') or rc.get('lat')
                comp_lon = rc.get('longitude') or rc.get('lng') or rc.get('lon')
                subj_lat = subject.get('latitude')
                subj_lon = subject.get('longitude')
                distance_miles = None
                if comp_lat is not None and comp_lon is not None and subj_lat is not None and subj_lon is not None:
                    try:
                        lat1 = math.radians(float(subj_lat))
                        lon1 = math.radians(float(subj_lon))
                        lat2 = math.radians(float(comp_lat))
                        lon2 = math.radians(float(comp_lon))
                        dlat = lat2 - lat1
                        dlon = lon2 - lon1
                        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
                        distance_miles = round(2 * 3958.8 * math.asin(math.sqrt(a)), 2)
                    except (TypeError, ValueError):
                        distance_miles = None

                # RapidAPI uses `dateSold` (epoch ms). Convert; fall back to today.
                import datetime as _dt
                ts_ms = rc.get('dateSold') or rc.get('lastSoldDate')
                if ts_ms:
                    try:
                        sale_date = _dt.datetime.fromtimestamp(int(ts_ms) / 1000).strftime('%Y-%m-%d')
                    except (TypeError, ValueError, OSError):
                        sale_date = _dt.date.today().strftime('%Y-%m-%d')
                else:
                    sale_date = _dt.date.today().strftime('%Y-%m-%d')

                # Year built is not in the search-results payload. Leave None
                # so the valuation step can skip the age adjustment cleanly.
                year_built = rc.get('yearBuilt') or rc.get('year_built')

                comp_obj = None
                if official_data and sale_price > 0:
                    comp_obj = {
                        'address': official_data['address'], 'sbl': official_data['sbl'],
                        'sale_price': sale_price,
                        'sale_date': sale_date,
                        'sqft': sqft or official_data['sqft'], 'acreage': acreage or official_data['acreage'],
                        'bedrooms': rc.get('bedrooms', official_data['bedrooms']),
                        'bathrooms': rc.get('bathrooms', official_data['bathrooms']),
                        'year_built': year_built or official_data['year_built'],
                        'assessment_2026': official_data.get('assessment_2026', 0),
                        'zpid': zpid, 'status': 'VERIFIED',
                        'distance_miles': distance_miles,
                    }
                elif sale_price > 0 and sqft > 0:
                    comp_obj = {
                        'address': full_addr, 'sbl': 'UNVERIFIED',
                        'sale_price': sale_price, 'sale_date': sale_date,
                        'sqft': sqft, 'acreage': acreage,
                        'bedrooms': rc.get('bedrooms', 0), 'bathrooms': rc.get('bathrooms', 0),
                        'year_built': year_built or 0,
                        'assessment_2026': 0,
                        'zpid': zpid, 'status': 'UNVERIFIED',
                        'distance_miles': distance_miles,
                    }

                if comp_obj:
                    # Ensure distance_miles column exists (migration is idempotent)
                    cursor.execute("PRAGMA table_info(sales_comps)")
                    _existing = {row[1] for row in cursor.fetchall()}
                    if 'distance_miles' not in _existing:
                        cursor.execute("ALTER TABLE sales_comps ADD COLUMN distance_miles REAL")
                        conn.commit()
                    cursor.execute("""
                        INSERT OR REPLACE INTO sales_comps (target_property_id, address, sbl, sale_price, sale_date, sqft, acreage, bedrooms, bathrooms, year_built, zpid, status, assessment_2026, distance_miles)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (subject_id, comp_obj['address'], comp_obj['sbl'], comp_obj['sale_price'], comp_obj['sale_date'],
                         comp_obj['sqft'], comp_obj['acreage'], comp_obj['bedrooms'], comp_obj['bathrooms'], comp_obj['year_built'],
                         comp_obj['zpid'], comp_obj['status'], comp_obj.get('assessment_2026', 0), comp_obj.get('distance_miles')))
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
        """Similarity scoring out of 100. Weights redistribute when a
        dimension is missing so 'no data' doesn't tank an otherwise good comp.
        Defaults: Sqft 40, Age 30, Acreage 20, Distance 10."""
        def normalize(val, target, tolerance):
            if target == 0 or val == 0: return None
            return max(0, 1 - (abs(val - target) / (target * tolerance)))

        subj_year = subject.get('year_built', 0)
        if renovation_year:
            subj_year = self.calculate_effective_year_built(subj_year, renovation_year)

        sqft_n = normalize(comp.get('sqft', 0), subject.get('sqft', 0), 0.20)
        acre_n = normalize(comp.get('acreage', 0), subject.get('acreage', 0), 0.50)

        comp_year = comp.get('year_built', 0)
        if comp_year and subj_year:
            age_n = max(0, 1 - (abs(comp_year - subj_year) / 50))
        else:
            age_n = None

        dist = comp.get('distance_miles')
        if dist is None: dist = 0.5
        dist_n = max(0, 1 - (dist / 5))

        # Weighted average over available dimensions, scaled back to 0-100.
        parts = [(sqft_n, 40), (age_n, 30), (acre_n, 20), (dist_n, 10)]
        avail = [(n, w) for n, w in parts if n is not None]
        if not avail:
            return 0.0
        total_w = sum(w for _, w in avail)
        score = sum(n * w for n, w in avail) / total_w * 100
        return round(score, 1)

    def calculate_valuation(self, subject, comps, adjs=None, renovation_year=None,
                            best_n: int = 5, condition_factor: float = 1.0):
        """Sales-comparison valuation with median+IQR outlier filter and a
        best-N selection. Returns a rich result dict (not just market_value)
        so callers can show defensible breakdowns.

        Returns dict with keys:
            market_value: median of best-N reconciled values
            range_low / range_high: IQR-bounded range (defensible "estimate")
            comps: list of all candidate comps with adjustment trail + flags
            used_count, considered_count: how many fed the final median
            adjustments_used: the per-municipality factor dict
        """
        from app.adjustments import get_adjustments

        def get_val(obj, key, default=0):
            val = obj.get(key)
            return val if val is not None else default

        if adjs is None:
            adjs = get_adjustments(subject.get('sbl'))

        # Sanity: need subject sqft to do meaningful math.
        if get_val(subject, 'sqft') == 0:
            return {
                "market_value": 0, "range_low": 0, "range_high": 0,
                "comps": [], "used_count": 0, "considered_count": 0,
                "adjustments_used": adjs,
            }

        subj_year = get_val(subject, 'year_built')
        if renovation_year:
            subj_year = self.calculate_effective_year_built(subj_year, renovation_year)

        raw_results = []
        for comp in comps:
            if comp.get('status') == 'REJECTED':
                continue
            adj_price = get_val(comp, 'sale_price', 0)
            if adj_price == 0:
                continue

            gla_adj = (get_val(subject, 'sqft') - get_val(comp, 'sqft')) * adjs['sqft']
            acre_adj = (get_val(subject, 'acreage') - get_val(comp, 'acreage')) * adjs['acre']
            bath_adj = (get_val(subject, 'bathrooms') - get_val(comp, 'bathrooms')) * adjs['bathroom']
            bed_adj = (get_val(subject, 'bedrooms') - get_val(comp, 'bedrooms')) * adjs['bedroom']
            comp_year = get_val(comp, 'year_built')
            age_adj = (subj_year - comp_year) * adjs['year_built'] if comp_year and subj_year else 0

            reconciled = adj_price + gla_adj + acre_adj + bath_adj + bed_adj + age_adj
            # Condition multiplier (user-set, default 1.0)
            reconciled *= condition_factor
            # Safety floor at 10% of sale price.
            reconciled = max(reconciled, adj_price * 0.1)

            score = self.calculate_similarity(subject, comp, renovation_year=renovation_year)

            raw_results.append({
                'address': comp['address'], 'sale_price': comp['sale_price'],
                'reconciled_value': reconciled, 'similarity_score': score,
                'adjustments': {
                    'gla': gla_adj, 'acreage': acre_adj, 'bath': bath_adj,
                    'bed': bed_adj, 'age': age_adj,
                },
                'zpid': comp.get('zpid'),
                'status': comp.get('status', 'VERIFIED'),
                'assessment_2026': comp.get('assessment_2026', 0),
                'assessment_2025': comp.get('assessment_2025', 0),
                'sqft': comp.get('sqft', 0),
                'year_built': comp.get('year_built', 0),
                'bedrooms': comp.get('bedrooms', 0),
                'bathrooms': comp.get('bathrooms', 0),
                'acreage': comp.get('acreage', 0),
                'sale_date': comp.get('sale_date'),
                'is_outlier': False,
                'used': False,
            })

        if not raw_results:
            return {
                "market_value": 0, "range_low": 0, "range_high": 0,
                "comps": [], "used_count": 0, "considered_count": 0,
                "adjustments_used": adjs,
            }

        # Median + 1.5×IQR (Tukey fence) outlier filter on reconciled_value.
        vals = sorted(r['reconciled_value'] for r in raw_results)
        n = len(vals)
        def _quantile(sorted_vals, q):
            if not sorted_vals:
                return 0
            idx = (len(sorted_vals) - 1) * q
            lo, hi = math.floor(idx), math.ceil(idx)
            if lo == hi:
                return sorted_vals[int(idx)]
            return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (idx - lo)
        q1 = _quantile(vals, 0.25)
        q3 = _quantile(vals, 0.75)
        iqr = q3 - q1
        lo_fence = q1 - 1.5 * iqr
        hi_fence = q3 + 1.5 * iqr
        for r in raw_results:
            r['is_outlier'] = not (lo_fence <= r['reconciled_value'] <= hi_fence)

        # Best-N: take top-N by similarity_score among non-outliers; if too few
        # survive the outlier filter, fall back to the top-N by similarity
        # ignoring the filter so we never return zero results.
        kept = [r for r in raw_results if not r['is_outlier']]
        if len(kept) < min(3, n):
            kept = list(raw_results)
        kept.sort(key=lambda r: r['similarity_score'], reverse=True)
        best = kept[:best_n] if best_n else kept
        for r in best:
            r['used'] = True

        used_vals = sorted(r['reconciled_value'] for r in best)
        if used_vals:
            mv = _quantile(used_vals, 0.5)
            lo = _quantile(used_vals, 0.25) if len(used_vals) > 1 else mv * 0.95
            hi = _quantile(used_vals, 0.75) if len(used_vals) > 1 else mv * 1.05
        else:
            mv = lo = hi = 0

        return {
            "market_value": mv,
            "range_low": lo,
            "range_high": hi,
            "comps": raw_results,
            "used_count": len(best),
            "considered_count": len(raw_results),
            "adjustments_used": adjs,
        }

    def add_manual_comp(self, property_id, address, price):
        """Verifies and adds a manual comp to the database."""
        # Look up the subject property's SBL so we route to the right county
        # even when the manual-comp address omits a town.
        conn0 = sqlite3.connect(self.db_path)
        cursor0 = conn0.cursor()
        cursor0.execute("SELECT sbl FROM properties WHERE id = ?", (property_id,))
        row0 = cursor0.fetchone()
        conn0.close()
        subj_sbl = row0[0] if row0 else None

        county = CountyFactory.get_county_handler(address_string=address, sbl=subj_sbl)
        official_p = county.search_address(address)
        if not official_p: return False
        
        data = county.get_full_rps_data(official_p.get('parcelgrid'))
        if not data: return False
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS sales_comps
                        (id INTEGER PRIMARY KEY, target_property_id INTEGER, address TEXT, sbl TEXT,
                         sale_price REAL, sale_date TEXT, sqft REAL, acreage REAL, bedrooms REAL,
                         bathrooms REAL, year_built INTEGER, zpid TEXT, status TEXT DEFAULT 'VERIFIED',
                         similarity_score REAL, is_outlier INTEGER DEFAULT 0,
                         assessment_2026 REAL, assessment_2025 REAL, distance_miles REAL)''')
        cursor.execute('''INSERT INTO sales_comps (target_property_id, address, sbl, sale_price, sale_date, sqft, acreage, bedrooms, bathrooms, year_built, status, assessment_2026)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'MANUAL', ?)''',
                    (property_id, data['address'], data['sbl'], price, '2025-01-01', data['sqft'], data['acreage'],
                     data['bedrooms'], data['bathrooms'], data['year_built'], data.get('assessment_2026', 0)))
        conn.commit()
        conn.close()
        return True
