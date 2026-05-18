from app.db import get_connection, is_postgres, upsert_sql, column_exists
from app.logging_safe import safe_addr
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

    def _fetch_rapidapi_comps(self, location, beds_min, beds_max, status=None):
        import requests
        from app.cache import get_rapidapi_cached, set_rapidapi_cached
        from app.comp_source import is_orpts, fetch_orpts_sold

        # Comp-source switch — when counsel rejects RapidAPI persistence we
        # flip COMP_SOURCE=orpts in prod env vars; no code change required.
        if is_orpts():
            return fetch_orpts_sold(location, beds_min, beds_max)

        # Cache check first — no upstream call if a recent identical query landed.
        cached = get_rapidapi_cached(location, beds_min, beds_max, status)
        if cached is not None:
            return cached

        api_key = os.getenv("RAPIDAPI_KEY")
        if not api_key:
            return []

        url = "https://real-time-real-estate-data.p.rapidapi.com/search"
        headers = {
            "x-rapidapi-host": "real-time-real-estate-data.p.rapidapi.com",
            "x-rapidapi-key": api_key
        }
        params = {
            "location": location,
            "beds_min": beds_min,
            "beds_max": beds_max,
        }
        if status:
            params["home_status"] = status

        try:
            resp = requests.get(url, headers=headers, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json().get('data', [])
            set_rapidapi_cached(location, beds_min, beds_max, status, data)
            return data
        except Exception as e:
            print(f"RapidAPI fetch error: {e}")
            return []

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
                        conn = get_connection(self.db_path)
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

        # 3. Recover missing building data and historical assessment via RapidAPI
        if profile.get('sqft', 0) == 0 or profile.get('bedrooms', 0) == 0 or profile.get('assessment_2025', 0) == 0:
            try:
                town = county.get_town_from_identifier(identifier)
                market_data = self._fetch_rapidapi_comps(f"{profile['address']}, {town}, NY", 0, 99)
                if market_data:
                    md = market_data[0]
                    rf = md.get('resoFacts', {})
                    if profile.get('sqft', 0) == 0:
                        profile['sqft'] = md.get('livingArea', md.get('area', 0))
                    if profile.get('bedrooms', 0) == 0:
                        profile['bedrooms'] = md.get('bedrooms', md.get('beds', 0))
                    if profile.get('bathrooms', 0) == 0:
                        profile['bathrooms'] = md.get('bathrooms', md.get('baths', 0))
                    if profile.get('year_built', 0) == 0:
                        profile['year_built'] = md.get('yearBuilt', md.get('year_built', 0))
                    
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
            conn = get_connection(self.db_path)
            c = conn.cursor()
            if not column_exists(c, 'properties', 'sbl'):
                conn.close()
                return None
            # COLLATE NOCASE is SQLite-only; ILIKE is Postgres-only. Use a
            # case-insensitive comparison that works on both by lowercasing
            # both sides.
            c.execute(
                "SELECT * FROM properties WHERE LOWER(address) LIKE LOWER(?) AND sbl IS NOT NULL",
                (pattern,),
            )
            rows = [dict(r) for r in c.fetchall()]
            conn.close()
        except Exception:
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
        conn = get_connection(self.db_path)
        cursor = conn.cursor()

        # 1. ALWAYS ensure table exists first
        # Legacy SQLite-only auto-migration. For new DBs, init_schema() in
        # db.py created the table at startup with all columns; this block
        # only does work for old SQLite files predating that. Postgres skips
        # it entirely because PRAGMA table_info doesn't exist there.
        if not is_postgres():
            cursor.execute('''CREATE TABLE IF NOT EXISTS properties
                            (id INTEGER PRIMARY KEY, address TEXT, sbl TEXT, sqft REAL, acreage REAL,
                             bedrooms REAL, bathrooms REAL, year_built INTEGER, assessment_2025 REAL, assessment_2026 REAL)''')
            cursor.execute("PRAGMA table_info(properties)")
            cols = [c[1] for c in cursor.fetchall()]
            for col, ddl in [
                ('assessment_2025',  'ALTER TABLE properties ADD COLUMN assessment_2025 REAL'),
                ('assessment_2026',  'ALTER TABLE properties ADD COLUMN assessment_2026 REAL'),
                ('latitude',         'ALTER TABLE properties ADD COLUMN latitude REAL'),
                ('longitude',        'ALTER TABLE properties ADD COLUMN longitude REAL'),
                ('zip',              'ALTER TABLE properties ADD COLUMN zip TEXT'),
                ('property_class',   'ALTER TABLE properties ADD COLUMN property_class TEXT'),
                ('condition_code',   'ALTER TABLE properties ADD COLUMN condition_code TEXT'),
                ('grade',            'ALTER TABLE properties ADD COLUMN grade TEXT'),
                ('basement_type',    'ALTER TABLE properties ADD COLUMN basement_type TEXT'),
                ('heat_type',        'ALTER TABLE properties ADD COLUMN heat_type TEXT'),
                ('style',            'ALTER TABLE properties ADD COLUMN style TEXT'),
                ('is_flood_zone',    'ALTER TABLE properties ADD COLUMN is_flood_zone INTEGER DEFAULT 0'),
                ('nuisance_rail',    'ALTER TABLE properties ADD COLUMN nuisance_rail INTEGER DEFAULT 0'),
                ('nuisance_highway', 'ALTER TABLE properties ADD COLUMN nuisance_highway INTEGER DEFAULT 0'),
                ('amenity_park',     'ALTER TABLE properties ADD COLUMN amenity_park INTEGER DEFAULT 0'),
            ]:
                if col not in cols:
                    cursor.execute(ddl)
        
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
                                property_class = COALESCE(NULLIF(?, ''), property_class),
                                condition_code = COALESCE(NULLIF(?, ''), condition_code),
                                grade = COALESCE(NULLIF(?, ''), grade),
                                basement_type = COALESCE(NULLIF(?, ''), basement_type),
                                heat_type = COALESCE(NULLIF(?, ''), heat_type),
                                style = COALESCE(NULLIF(?, ''), style),
                                is_flood_zone = COALESCE(?, is_flood_zone),
                                nuisance_rail = COALESCE(?, nuisance_rail),
                                nuisance_highway = COALESCE(?, nuisance_highway),
                                amenity_park = COALESCE(?, amenity_park)
                              WHERE id = ?''',
                           (subject_data.get('sqft', 0), subject_data.get('bedrooms', 0),
                            subject_data.get('bathrooms', 0), subject_data.get('year_built', 0),
                            subject_data.get('assessment_2025', 0), subject_data.get('assessment_2026', 0),
                            subject_data.get('latitude'), subject_data.get('longitude'), subject_data.get('zip'),
                            subject_data.get('property_class'),
                            subject_data.get('condition_code'), subject_data.get('grade'),
                            subject_data.get('basement_type'), subject_data.get('heat_type'),
                            subject_data.get('style'),
                            subject_data.get('is_flood_zone'), subject_data.get('nuisance_rail'),
                            subject_data.get('nuisance_highway'), subject_data.get('amenity_park'),
                            row_id))
            
        conn.commit()
        conn.close()
        return row_id

    def discover_comps_live(self, subject, subject_id, force_verify=False):
        """Streams comps from RapidAPI, verifies them, and persists to DB immediately."""
        # Ensure sales_comps schema is up to date BEFORE any early returns so
        # downstream SELECTs (in main.py) don't hit missing columns when the
        # API key is absent.
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        # Legacy SQLite-only auto-migration (see note above the properties
        # equivalent in ensure_property). Postgres skips this — schema already
        # came from schema_postgres.sql at init_schema() time.
        if not is_postgres():
            cursor.execute('''CREATE TABLE IF NOT EXISTS sales_comps
                            (id INTEGER PRIMARY KEY, target_property_id INTEGER, address TEXT, sbl TEXT,
                             sale_price REAL, sale_date TEXT, sqft REAL, acreage REAL, bedrooms REAL,
                             bathrooms REAL, year_built INTEGER, zpid TEXT, status TEXT DEFAULT 'VERIFIED',
                             similarity_score REAL, is_outlier INTEGER DEFAULT 0,
                             assessment_2026 REAL, assessment_2025 REAL, distance_miles REAL,
                             rejection_reason TEXT, is_selected INTEGER DEFAULT 0, grade TEXT)''')
            cursor.execute("PRAGMA table_info(sales_comps)")
            cols = [c[1] for c in cursor.fetchall()]
            for col, ddl in [
                ('zpid',             "ALTER TABLE sales_comps ADD COLUMN zpid TEXT"),
                ('status',           "ALTER TABLE sales_comps ADD COLUMN status TEXT DEFAULT 'VERIFIED'"),
                ('assessment_2026',  "ALTER TABLE sales_comps ADD COLUMN assessment_2026 REAL"),
                ('assessment_2025',  "ALTER TABLE sales_comps ADD COLUMN assessment_2025 REAL"),
                ('distance_miles',   "ALTER TABLE sales_comps ADD COLUMN distance_miles REAL"),
                ('rejection_reason', "ALTER TABLE sales_comps ADD COLUMN rejection_reason TEXT"),
                ('is_selected',      "ALTER TABLE sales_comps ADD COLUMN is_selected INTEGER DEFAULT 0"),
                ('grade',            "ALTER TABLE sales_comps ADD COLUMN grade TEXT"),
                ('condition_code',   "ALTER TABLE sales_comps ADD COLUMN condition_code TEXT"),
                ('bldg_grade',       "ALTER TABLE sales_comps ADD COLUMN bldg_grade TEXT"),
                ('basement_type',    "ALTER TABLE sales_comps ADD COLUMN basement_type TEXT"),
                ('heat_type',        "ALTER TABLE sales_comps ADD COLUMN heat_type TEXT"),
                ('style',            "ALTER TABLE sales_comps ADD COLUMN style TEXT"),
                ('property_class',   "ALTER TABLE sales_comps ADD COLUMN property_class TEXT"),
                ('is_flood_zone',    "ALTER TABLE sales_comps ADD COLUMN is_flood_zone INTEGER DEFAULT 0"),
                ('nuisance_rail',    "ALTER TABLE sales_comps ADD COLUMN nuisance_rail INTEGER DEFAULT 0"),
                ('nuisance_highway', "ALTER TABLE sales_comps ADD COLUMN nuisance_highway INTEGER DEFAULT 0"),
                ('amenity_park',     "ALTER TABLE sales_comps ADD COLUMN amenity_park INTEGER DEFAULT 0"),
            ]:
                if col not in cols:
                    cursor.execute(ddl)

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

        conn = get_connection(self.db_path)
        cursor = conn.cursor()

        yield {"status": "searching", "message": f"Searching market sales for {subject['address']}..."}

        # Route by SBL — the bare street address can be in either county.
        county = CountyFactory.get_county_handler(address_string=subject['address'], sbl=subject.get('sbl'))
        town = county.get_town_from_identifier(subject['sbl'])
        location = f"{town}, NY"

        # Fetch RAR from SODA API
        from app.orpts import OrptsClient
        orpts_client = OrptsClient()
        subj_swis = subject.get('sbl', '')[:6]
        rates = orpts_client.get_municipal_rates(subj_swis)
        rar = rates.get('rar', 100.0)

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
            raw_comps = self._fetch_rapidapi_comps(location, beds_min, beds_max, "RECENTLY_SOLD")
            
            if not raw_comps:
                yield {"status": "searching", "message": "No specific matches. Trying broader search..."}
                raw_comps = self._fetch_rapidapi_comps(location, 0, 99, "RECENTLY_SOLD")

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
                    elif force_verify:
                        # Fallback to slow address search if forced
                        search_res = county.search_address(full_addr)
                        if search_res and search_res.get('parcelgrid'):
                            official_data = county.get_full_rps_data(search_res.get('parcelgrid'))
                except (CountyAPIError, Exception) as ve:
                    print(f"  verify skipped for {safe_addr(full_addr)}: {ve}")
                    official_data = None

                sqft = rc.get('livingArea') or rc.get('area') or 0
                acreage = rc.get('lotAreaValue') or 0
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
                tax_av_2025 = rc.get('taxAssessedValue') or 0
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
                        'assessment_2025': tax_av_2025,
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
                        'assessment_2025': tax_av_2025,
                        'zpid': zpid, 'status': 'UNVERIFIED',
                        'distance_miles': distance_miles,
                    }

                if comp_obj:
                    # Enforce Hard Filters
                    passes, reason = self._passes_hard_filters(subject, comp_obj)
                    if not passes:
                        yield {"status": "resuming", "message": f"Rejected by Hard Filter: {reason} ({comp_obj['address']})"}
                        continue

                    # Calculate Grade & Score immediately
                    comp_obj['similarity_score'] = self.calculate_similarity(subject, comp_obj, rar=rar)
                    comp_obj['grade'] = self.calculate_similarity_grade(subject, comp_obj)
                    comp_obj['is_selected'] = 0 # Default to unselected for human review

                    # distance_miles column existence is guaranteed by
                    # init_schema()/the earlier legacy migration block, so
                    # no need to PRAGMA-check here.
                    _comp_cols = [
                        'target_property_id', 'address', 'sbl', 'sale_price', 'sale_date', 'sqft', 'acreage',
                        'bedrooms', 'bathrooms', 'year_built', 'zpid', 'status', 'assessment_2026', 'assessment_2025',
                        'distance_miles', 'grade', 'similarity_score', 'is_selected',
                        'condition_code', 'bldg_grade', 'basement_type', 'heat_type', 'style', 'property_class',
                    ]
                    cursor.execute(
                        upsert_sql('sales_comps', _comp_cols, conflict_cols=['target_property_id', 'zpid']),
                        (subject_id, comp_obj['address'], comp_obj['sbl'], comp_obj['sale_price'], comp_obj['sale_date'],
                         comp_obj['sqft'], comp_obj['acreage'], comp_obj['bedrooms'], comp_obj['bathrooms'], comp_obj['year_built'],
                         comp_obj['zpid'], comp_obj['status'], comp_obj.get('assessment_2026', 0), comp_obj.get('assessment_2025', 0), comp_obj.get('distance_miles'),
                         comp_obj['grade'], comp_obj['similarity_score'], comp_obj['is_selected'],
                         comp_obj.get('condition_code', ''), comp_obj.get('grade', ''), comp_obj.get('basement_type', ''),
                         comp_obj.get('heat_type', ''), comp_obj.get('style', ''), comp_obj.get('property_class', '')))
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

    def _passes_hard_filters(self, subject, comp, valuation_date="2024-07-01"):
        """
        Enforce strict exclusion rules. Returns (True, "") or (False, "reason").
        """
        # 1. Geography Rule: Strict SWIS boundary (Village vs Town)
        subj_swis = subject.get('sbl', '')[:6]
        comp_swis = comp.get('sbl', '')[:6]
        if subj_swis and comp_swis and comp_swis != 'UNVERIFIED':
            # 135001 = Village, 135089 = Town. They must match exactly.
            if subj_swis in ['135001', '135089'] and comp_swis in ['135001', '135089']:
                if subj_swis != comp_swis:
                    return False, "Crosses Town/Village boundary"

        # 2. Temporal Rule: ±6 months of Valuation Date (Valuation Date is July 1 of prior year)
        # So for 2025 roll, val date is July 1, 2024. Window is Jan 1 2024 - Dec 31 2024.
        sale_date = comp.get('sale_date', '')
        if sale_date:
            try:
                import datetime as _dt
                s_date = _dt.datetime.strptime(sale_date, '%Y-%m-%d').date()
                v_date = _dt.datetime.strptime(valuation_date, '%Y-%m-%d').date()
                delta = abs((s_date - v_date).days)
                if delta > 183: # ~6 months
                    return False, "Sale date outside 12-month window"
            except ValueError:
                pass

        # 3. Arm's-Length Rule: <$100,000 transfers or obvious non-market status
        sale_price = comp.get('sale_price', 0)
        if sale_price < 100000:
            return False, "Non-arm's-length transfer (<$100k sale)"
            
        status = comp.get('status', '').upper()
        if 'FORECLOSURE' in status or 'SHORT_SALE' in status:
            return False, "Foreclosure or Short Sale"

        # 4. GLA Variance: Discard if > 20%
        subj_sqft = subject.get('sqft', 0)
        comp_sqft = comp.get('sqft', 0)
        if subj_sqft > 0 and comp_sqft > 0:
            variance = abs(comp_sqft - subj_sqft) / subj_sqft
            if variance > 0.20:
                return False, f"GLA variance > 20% ({variance:.1%})"

        return True, ""

    def calculate_effective_year_built(self, original_year, renovation_year):
        """Calculates a weighted Effective Year Built based on a major renovation."""
        if not renovation_year or renovation_year <= original_year:
            return original_year
        return int((original_year + renovation_year) / 2)

    def calculate_similarity(self, subject, comp, renovation_year=None, rar=100.0):
        """
        Calculates Total Score = (Similarity Index * 0.70) + (Advantage Index * 0.30)
        Similarity Index (0-100): Date, GLA, Style/Era, Grade/Condition.
        Advantage Index (0-100): Based on price/sqft vs target EMV/sqft.
        """
        import datetime as _dt
        
        # --- SIMILARITY INDEX (70%) ---
        sim_points = 0.0
        max_sim_points = 100.0

        # 1. Date (Max 25 pts)
        date_pts = 0
        sale_date_str = comp.get('sale_date')
        if sale_date_str:
            try:
                s_date = _dt.datetime.strptime(sale_date_str, '%Y-%m-%d').date()
                v_date = _dt.date(2024, 7, 1) # Valuation date
                days_diff = abs((s_date - v_date).days)
                if days_diff <= 183:
                    date_pts = max(0, 25 * (1 - (days_diff / 183)))
            except ValueError:
                pass
        sim_points += date_pts

        # 2. GLA (Max 30 pts)
        gla_pts = 0
        subj_sqft = subject.get('sqft', 0)
        comp_sqft = comp.get('sqft', 0)
        if subj_sqft > 0 and comp_sqft > 0:
            var = abs(comp_sqft - subj_sqft) / subj_sqft
            if var <= 0.05:
                gla_pts = 30
            elif var <= 0.20:
                # Linear deduct between 5% and 20%
                gla_pts = max(0, 30 * (1 - ((var - 0.05) / 0.15)))
        sim_points += gla_pts

        # 3. Style & Era (Max 25 pts)
        style_pts = 0
        if subject.get('style') and comp.get('style') and subject.get('style') == comp.get('style'):
            style_pts += 15
        
        subj_year = subject.get('year_built', 0)
        if renovation_year:
            subj_year = self.calculate_effective_year_built(subj_year, renovation_year)
        comp_year = comp.get('year_built', 0)
        if subj_year and comp_year and abs(subj_year - comp_year) <= 10:
            style_pts += 10
        sim_points += style_pts

        # 4. Grade/Condition (Max 20 pts)
        cond_pts = 0
        subj_cond = (subject.get('condition_code') or '').lower()
        comp_cond = (comp.get('condition_code') or '').lower()
        if subj_cond and comp_cond:
            if subj_cond == comp_cond:
                cond_pts = 20
            else:
                cond_pts = 5 # arbitrary low value for mismatch
        else:
            cond_pts = 10 # average if missing data
        sim_points += cond_pts

        similarity_index = (sim_points / max_sim_points) * 100

        # --- ADVANTAGE INDEX (30%) ---
        # Calculate Target EMV/sqft = (Assessed Value / RAR) / Target GLA
        target_emv_sqft = 0
        av = subject.get('assessment_2025', 0)
        if av > 0 and subj_sqft > 0 and rar > 0:
            target_emv = av / (rar / 100.0)
            target_emv_sqft = target_emv / subj_sqft

        # Comp Price/sqft = Sale Price / Comp GLA
        comp_price_sqft = 0
        sale_price = comp.get('sale_price', 0)
        if sale_price > 0 and comp_sqft > 0:
            comp_price_sqft = sale_price / comp_sqft

        advantage_index = 0
        # The prompt says: "Rank comps inversely by their price per sqft. Award 100 points to the comp with the lowest price per sqft relative to the target's EMV per sqft."
        # We'll calculate a relative ratio. Lower comp_price_sqft compared to target_emv_sqft is better.
        if target_emv_sqft > 0 and comp_price_sqft > 0:
            ratio = comp_price_sqft / target_emv_sqft
            # If ratio is 1.0 (they match), advantage is 50.
            # If ratio is 0.5 (comp is half the price of target), advantage is high (e.g. 100)
            # If ratio is 1.5 (comp is way more expensive), advantage is low (0)
            advantage_index = max(0, min(100, 100 - ((ratio - 0.5) * 100)))
        else:
            advantage_index = 50 # Default if data missing

        total_score = (similarity_index * 0.70) + (advantage_index * 0.30)
        return round(total_score, 1)

    def calculate_similarity_grade(self, subject, comp, renovation_year=None, valuation_date="2025-07-01"):
        """
        Assigns a letter grade (A, B, C, F) based on similarity score and sale date proximity.
        NYS BARs prioritize sales within 12 months of the Valuation Date.
        """
        base_score = self.calculate_similarity(subject, comp, renovation_year)
        
        # Date Proximity Penalty
        import datetime
        try:
            val_dt = datetime.datetime.strptime(valuation_date, "%Y-%m-%d").date()
            sale_dt = datetime.datetime.strptime(comp.get('sale_date', valuation_date), "%Y-%m-%d").date()
        except:
            val_dt = datetime.date(2025, 7, 1)
            sale_dt = val_dt
            
        months_diff = abs((val_dt.year - sale_dt.year) * 12 + (val_dt.month - sale_dt.month))
        
        # Deduct 2 points for every month beyond the ideal 12-month window
        date_penalty = 0
        if months_diff > 12:
            date_penalty = min(30, (months_diff - 12) * 2)
            
        final_score = max(0, base_score - date_penalty)
        
        if final_score >= 85: return "A"
        if final_score >= 70: return "B"
        if final_score >= 50: return "C"
        return "F"

    def calculate_valuation(self, subject, comps, adjs=None, renovation_year=None,
                            best_n: int = 3, condition_factor: float = 1.0, enforce_selection=False):
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
            
            # PHASE 2 ENFORCEMENT: If enforcing selection, skip unselected comps
            if enforce_selection and not comp.get('is_selected'):
                continue

            adj_price = get_val(comp, 'sale_price', 0)
            if adj_price == 0:
                continue

            try:
                gla_adj = (get_val(subject, 'sqft') - get_val(comp, 'sqft')) * adjs.get('sqft', 150.0)
                acre_adj = (get_val(subject, 'acreage') - get_val(comp, 'acreage')) * adjs.get('acre', 50000.0)
                bath_adj = (get_val(subject, 'bathrooms') - get_val(comp, 'bathrooms')) * adjs.get('bathroom', 15000.0)
                bed_adj = (get_val(subject, 'bedrooms') - get_val(comp, 'bedrooms')) * adjs.get('bedroom', 10000.0)
                comp_year = get_val(comp, 'year_built')
                if comp_year and subj_year:
                    age_diff = subj_year - comp_year
                    # Cap age difference at 50 years to prevent massive historical penalties
                    age_diff = max(-50, min(50, age_diff))
                    age_adj = age_diff * adjs.get('year_built', 1000.0)
                else:
                    age_adj = 0
                
                # New Adjustments
                # Finished Basement
                subj_bsmt = 1 if (subject.get('basement_type') or '').lower() == 'finished' else 0
                comp_bsmt = 1 if (comp.get('basement_type') or '').lower() == 'finished' else 0
                basement_adj = (subj_bsmt - comp_bsmt) * adjs.get('finished_basement', 20000.0)
                
                # Flood Zone (Negative value: Subject has it, Comp doesn't -> subtract from Comp)
                subj_flood = 1 if subject.get('is_flood_zone') else 0
                comp_flood = 1 if comp.get('is_flood_zone') else 0
                fz_adj = (subj_flood - comp_flood) * -adjs.get('flood_zone', 25000.0)
                
                # Nuisance (Negative value)
                subj_n = 1 if subject.get('nuisance_rail') or subject.get('nuisance_highway') else 0
                comp_n = 1 if comp.get('nuisance_rail') or comp.get('nuisance_highway') else 0
                nuisance_adj = (subj_n - comp_n) * -adjs.get('nuisance', 15000.0)

                reconciled = adj_price + gla_adj + acre_adj + bath_adj + bed_adj + age_adj + basement_adj + fz_adj + nuisance_adj
                # Condition multiplier (user-set, default 1.0)
                reconciled *= condition_factor
                # Safety floor at 10% of sale price.
                reconciled = max(reconciled, adj_price * 0.1)

                score = self.calculate_similarity(subject, comp, renovation_year=renovation_year)

                raw_results.append({
                    'address': comp['address'], 'sale_price': comp['sale_price'],
                    'reconciled_value': reconciled, 'similarity_score': score,
                    'grade': comp.get('grade', 'C'),
                    'is_selected': comp.get('is_selected', 0),
                    'adjustments': {
                        'gla': gla_adj, 'acreage': acre_adj, 'bath': bath_adj,
                        'bed': bed_adj, 'age': age_adj, 'basement': basement_adj,
                        'flood_zone': fz_adj, 'nuisance': nuisance_adj
                    },
                    'zpid': comp.get('zpid'),
                    'status': comp.get('status', 'VERIFIED'),
                    'assessment_2026': comp.get('assessment_2026', 0),
                    'assessment_2025': comp.get('assessment_2025', 0),
                    'distance_miles': comp.get('distance_miles'),
                    'sqft': comp.get('sqft', 0),
                    'year_built': comp.get('year_built', 0),
                    'bedrooms': comp.get('bedrooms', 0),
                    'bathrooms': comp.get('bathrooms', 0),
                    'acreage': comp.get('acreage', 0),
                    'sale_date': comp.get('sale_date'),
                    'is_outlier': False,
                    'used': False,
                })
            except Exception as e:
                print(f"Skipping comp {safe_addr(comp.get('address'))} in valuation due to error: {e}")

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
            if enforce_selection:
                r['is_outlier'] = False
            else:
                r['is_outlier'] = not (lo_fence <= r['reconciled_value'] <= hi_fence)

        # Best-N: take top-N by similarity_score among non-outliers; if too few
        # survive the outlier filter, fall back to the top-N by similarity
        # ignoring the filter so we never return zero results.
        kept = [r for r in raw_results if not r['is_outlier']]
        if len(kept) < min(3, n):
            kept = list(raw_results)
        kept.sort(key=lambda r: r['similarity_score'], reverse=True)
        
        if enforce_selection:
            best = kept
        else:
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
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        
        # Check limit
        cursor.execute("SELECT COUNT(*) FROM sales_comps WHERE target_property_id = ? AND status = 'MANUAL'", (property_id,))
        count = cursor.fetchone()[0]
        if count >= 5:
            conn.close()
            return False, "Maximum of 5 manual comps allowed."

        # Look up the subject property
        cursor.execute("SELECT * FROM properties WHERE id = ?", (property_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return False, "Subject property not found."
        subject = dict(row)
        subj_sbl = subject.get('sbl')
        
        county = CountyFactory.get_county_handler(address_string=address, sbl=subj_sbl)
        official_p = county.search_address(address)
        if not official_p: 
            conn.close()
            return False, "Address not found in municipal records."
        
        data = county.get_full_rps_data(official_p.get('parcelgrid'))
        if not data: 
            conn.close()
            return False, "Could not fetch property details."
            
        import datetime
        sale_date = datetime.date.today().strftime('%Y-%m-%d')
            
        # Calculate distance
        distance_miles = None
        comp_lat = data.get('latitude')
        comp_lon = data.get('longitude')
        subj_lat = subject.get('latitude')
        subj_lon = subject.get('longitude')
        if comp_lat and comp_lon and subj_lat and subj_lon:
            try:
                import math
                lat1 = math.radians(float(subj_lat))
                lon1 = math.radians(float(subj_lon))
                lat2 = math.radians(float(comp_lat))
                lon2 = math.radians(float(comp_lon))
                dlat = lat2 - lat1
                dlon = lon2 - lon1
                a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
                distance_miles = round(2 * 3958.8 * math.asin(math.sqrt(a)), 2)
            except (TypeError, ValueError):
                pass
                
        # Build comp object to calculate scores
        comp_obj = {
            'address': data['address'],
            'sbl': data['sbl'],
            'sale_price': float(price),
            'sale_date': sale_date,
            'sqft': data.get('sqft', 0),
            'acreage': data.get('acreage', 0),
            'bedrooms': data.get('bedrooms', 0),
            'bathrooms': data.get('bathrooms', 0),
            'year_built': data.get('year_built', 0),
            'condition_code': data.get('condition_code', ''),
            'grade': data.get('grade', ''),
            'style': data.get('style', ''),
            'is_selected': 1,
            'status': 'MANUAL'
        }
        
        # Fetch RAR for score calculation
        try:
            from app.orpts import OrptsClient
            orpts_client = OrptsClient()
            subj_swis = subj_sbl[:6] if subj_sbl else ''
            rates = orpts_client.get_municipal_rates(subj_swis)
            rar = rates.get('rar', 100.0)
        except Exception:
            rar = 100.0
            
        comp_obj['similarity_score'] = self.calculate_similarity(subject, comp_obj, rar=rar)
        comp_obj['grade'] = self.calculate_similarity_grade(subject, comp_obj)
        
        # Schema is guaranteed by init_schema() at startup + the legacy
        # SQLite migration block in discover_comps_live. No need to recreate
        # or check columns here.
        cursor.execute('''INSERT INTO sales_comps (target_property_id, address, sbl, sale_price, sale_date, sqft, acreage, bedrooms, bathrooms, year_built, status, assessment_2026, distance_miles, similarity_score, grade, is_selected)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'MANUAL', ?, ?, ?, ?, 1)''',
                    (property_id, comp_obj['address'], comp_obj['sbl'], comp_obj['sale_price'], comp_obj['sale_date'],
                     comp_obj['sqft'], comp_obj['acreage'], comp_obj['bedrooms'], comp_obj['bathrooms'],
                     comp_obj['year_built'], data.get('assessment_2026', 0), distance_miles, comp_obj['similarity_score'], comp_obj['grade']))
        conn.commit()
        conn.close()
        return True, "Added successfully."
