import requests
import json
import sqlite3
import time

DB_PATH = 'grievance_data.db'
API_BASE_URL = "https://gis.dutchessny.gov/parcelaccess/asp"

# Final mapping of comp addresses to their verified search parameters
COMPS_DATA = {
    "67 N Parsonage St": [
        {"address": "65 N Parsonage St", "swis": "135001", "sale_price": 750000, "sale_date": "2025-10-07", "search": {"number": "65", "street": "PARSONAGE", "predir": "N"}},
        {"address": "72 Old Farm Rd", "swis": "135089", "sale_price": 950000, "sale_date": "2025-12-15", "search": {"number": "72", "street": "OLD FARM"}},
        {"address": "1557 Centre Rd", "swis": "132400", "sale_price": 700018, "sale_date": "2025-02-12", "search": {"number": "1557", "street": "CENTRE"}},
        {"address": "38 Chestnut St", "swis": "135001", "sale_price": 1450000, "sale_date": "2026-01-05", "search": {"number": "38", "street": "CHESTNUT"}},
        {"address": "14 Oak St", "swis": "135001", "sale_price": 640000, "sale_date": "2026-01-23", "search": {"number": "14", "street": "OAK"}}
    ],
    "33 Cedar Heights Rd": [
        {"address": "2 Shady Ln", "swis": "134889", "sale_price": 465000, "sale_date": "2025-05-25", "search": {"number": "2", "street": "SHADY"}},
        {"address": "84 Stone Church Rd", "swis": "135089", "sale_price": 513000, "sale_date": "2025-02-19", "search": {"number": "84", "street": "STONE CHURCH"}},
        {"address": "9 3rd Ave", "swis": "132400", "sale_price": 489000, "sale_date": "2025-03-31", "search": {"number": "9", "street": "THIRD"}},
        {"address": "16 Howland Ave", "swis": "135089", "sale_price": 443000, "sale_date": "2025-05-02", "search": {"number": "16", "street": "HOWLAND "}}, # Trailing space required
        {"address": "15 Kalina Dr", "swis": "134889", "sale_price": 520000, "sale_date": "2025-02-10", "search": {"number": "15", "street": "KALINA"}},
        {"address": "26 Birchwood Dr", "swis": "134889", "sale_price": 482000, "sale_date": "2026-03-18", "search": {"number": "26", "street": "BIRCHWOOD"}},
        {"address": "9 Mountain View Ct", "swis": "134889", "sale_price": 465000, "sale_date": "2026-02-24", "search": {"number": "9", "street": "MOUNTAIN VIEW"}}
    ]
}

def get_full_data(parcelgrid):
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

    for subject_addr, comps in COMPS_DATA.items():
        print(f"Processing comps for: {subject_addr}...")
        cursor.execute("SELECT id FROM properties WHERE address = ?", (subject_addr,))
        row = cursor.fetchone()
        if not row: continue
        target_id = row[0]

        for comp in comps:
            print(f"  Enriching {comp['address']}...")
            params = comp['search']
            params['swis'] = comp['swis']
            resp = requests.get(f"{API_BASE_URL}/search_extract_addresses.asp", params=params).json()
            
            if resp.get('success') and resp.get('data'):
                grid = resp['data'][0]['parcelgrid']
                official = get_full_data(grid)
                if official:
                    cursor.execute("""
                        INSERT OR REPLACE INTO sales_comps 
                        (address, sbl, sale_price, sale_date, sqft, acreage, bedrooms, bathrooms, year_built, target_property_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        comp['address'], grid, comp['sale_price'], comp['sale_date'],
                        official['sqft'], official['acreage'], official['bedrooms'], official['bathrooms'], 
                        official['year_built'], target_id
                    ))
            else:
                print(f"    FAILED search for {comp['address']}")
            time.sleep(0.5)

    conn.commit()
    conn.close()
    print("Enrichment complete.")

if __name__ == "__main__":
    main()
