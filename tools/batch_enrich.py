import requests
import json
import sqlite3
import time
import os

# Configuration
DB_PATH = 'grievance_data.db'
API_BASE_URL = "https://gis.dutchessny.gov/parcelaccess/asp"

# Subjects to Ensure are in DB
SUBJECTS = [
    {
        "address": "67 N Parsonage St",
        "sbl": "13500100617000156384180000",
        "sqft": 2580, "acreage": 0.43, "bedrooms": 4, "bathrooms": 2.5, "year_built": 2006,
        "assessment_2025": 948300, "assessment_2026": 986200
    },
    {
        "address": "33 Cedar Heights Rd",
        "sbl": "13508900627100002991200000",
        "sqft": 0, "acreage": 2.0, "bedrooms": 0, "bathrooms": 0, "year_built": 0, # To be enriched
        "assessment_2025": 680200, "assessment_2026": 0 # Unknown yet
    }
]

# Comps for 33 Cedar
CEDAR_COMPS = [
    {"address": "2 Shady Ln", "swis": "135089", "sale_price": 465000, "sale_date": "2025-05-25"},
    {"address": "84 Stone Church Rd", "swis": "135089", "sale_price": 513000, "sale_date": "2025-02-19"},
    {"address": "9 3rd Ave", "swis": "135089", "sale_price": 479000, "sale_date": "2025-03-31"},
    {"address": "16 Howland Ave", "swis": "135089", "sale_price": 443000, "sale_date": "2025-05-02"},
    {"address": "15 Kalina Dr", "swis": "135089", "sale_price": 520000, "sale_date": "2025-02-10"},
    {"address": "26 Birchwood Dr", "swis": "135089", "sale_price": 482000, "sale_date": "2026-03-18"},
    {"address": "9 Mountain View Ct", "swis": "135089", "sale_price": 465000, "sale_date": "2026-02-24"},
]

def search_parcel(address, swis=""):
    """Robust search for parcel info."""
    parts = address.split(' ', 1)
    number = parts[0]
    street_full = parts[1].upper()
    
    # Abbreviation mapping for API compatibility
    street_full = street_full.replace("LANE", "LN").replace("ROAD", "RD").replace("AVENUE", "AVE").replace("DRIVE", "DR").replace("COURT", "CT")

    predir = ""
    if " N " in street_full:
        predir = "N"
        street = street_full.replace("N ", "").split(' ')[0]
    else:
        street = street_full.split(' ')[0]

    params = {'number': number, 'street': street, 'predir': predir, 'swis': swis}
    resp = requests.get(f"{API_BASE_URL}/search_extract_addresses.asp", params=params)
    data = resp.json()
    
    if data.get('success') and data.get('data'):
        return data['data'][0]
    return None

def get_full_data(parcelgrid):
    """Fetch all official RPS data for a parcelgrid."""
    resp = requests.post(f"{API_BASE_URL}/search_extract_parcelgrids.asp", data={'parcelgrid': parcelgrid})
    rps_list = resp.json().get('data', [])
    if not rps_list: return None
    primary = rps_list[0]
    
    params = {
        'parcelid': primary['parcel_id'],
        'county': primary['swis'][:2],
        'town': primary['swis'][2:4],
        'village': primary['swis'][4:6]
    }
    details_resp = requests.get(f"{API_BASE_URL}/get_property_details.asp", params=params).json()
    details = details_resp.get('data', {})
    res_bldg = details.get('resbldg', [{}])[0]
    
    return {
        'sbl': parcelgrid,
        'sqft': res_bldg.get('sfla', 0),
        'acreage': primary.get('acreage', 0),
        'bedrooms': res_bldg.get('nbr_bedrooms', 0),
        'bathrooms': res_bldg.get('nbr_full_baths', 0) + (0.5 * res_bldg.get('nbr_half_baths', 0)),
        'year_built': res_bldg.get('yr_built', 0),
        'assessment_2025': primary.get('total_av', 0)
    }

def main():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. Update/Insert Subjects
    subject_ids = {}
    for s in SUBJECTS:
        print(f"Ensuring subject: {s['address']}...")
        if s['sqft'] == 0:
            official = get_full_data(s['sbl'])
            if official: s.update(official)

        cursor.execute("""
            INSERT OR REPLACE INTO properties 
            (address, sbl, sqft, acreage, bedrooms, bathrooms, year_built, assessment_2025, assessed_value_2026)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (s['address'], s['sbl'], s['sqft'], s['acreage'], s['bedrooms'], s['bathrooms'], s['year_built'], s['assessment_2025'], s['assessment_2026']))
        
        cursor.execute("SELECT id FROM properties WHERE sbl = ?", (s['sbl'],))
        subject_ids[s['address']] = cursor.fetchone()[0]

    # 2. Enrich Comps for 33 Cedar
    target_id = subject_ids["33 Cedar Heights Rd"]
    for comp in CEDAR_COMPS:
        print(f"Enriching comp: {comp['address']}...")
        p_data = search_parcel(comp['address'], comp['swis'])
        if not p_data:
            print(f"  FAILED to find {comp['address']}")
            continue
            
        official = get_full_data(p_data['parcelgrid'])
        if not official: continue
        
        cursor.execute("""
            INSERT OR REPLACE INTO sales_comps 
            (address, sbl, sale_price, sale_date, sqft, acreage, bedrooms, bathrooms, year_built, target_property_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            comp['address'], official['sbl'], comp['sale_price'], comp['sale_date'],
            official['sqft'], official['acreage'], official['bedrooms'], official['bathrooms'], 
            official['year_built'], target_id
        ))
        time.sleep(0.5)

    conn.commit()
    conn.close()
    print("Batch processing complete.")

if __name__ == "__main__":
    main()
