import requests
import json
import sqlite3
import time
import os

# Configuration
DB_PATH = 'grievance_data.db'
API_BASE_URL = "https://gis.dutchessny.gov/parcelaccess/asp"

# Curated Comps from User
COMPS = [
    {"address": "65 N Parsonage St", "city": "Rhinebeck", "swis": "135001", "sale_price": 750000, "sale_date": "2025-10-07"},
    {"address": "72 Old Farm Rd", "city": "Rhinebeck", "swis": "135089", "sale_price": 950000, "sale_date": "2025-12-15"},
    {"address": "1557 Centre Rd", "city": "Rhinebeck", "swis": "135089", "sale_price": 650000, "sale_date": "2025-12-24"},
    {"address": "38 Chestnut St", "city": "Rhinebeck", "swis": "135001", "sale_price": 1450000, "sale_date": "2026-01-05"},
    {"address": "14 Oak St", "city": "Rhinebeck", "swis": "135001", "sale_price": 640000, "sale_date": "2026-01-23"},
]

def search_parcel(address_dict):
    """Finds the parcelgrid and parcelid for an address."""
    import re
    raw_addr = address_dict['address'].upper().strip()
    
    # Standardize prefixes
    if raw_addr.startswith("NORTH "): raw_addr = raw_addr.replace("NORTH ", "N ", 1)
    elif raw_addr.startswith("SOUTH "): raw_addr = raw_addr.replace("SOUTH ", "S ", 1)
    elif raw_addr.startswith("EAST "): raw_addr = raw_addr.replace("EAST ", "E ", 1)
    elif raw_addr.startswith("WEST "): raw_addr = raw_addr.replace("WEST ", "W ", 1)

    # Basic Regex for Number, Prefix, Street
    # Matches: "123 Main", "123 N Main", "123 North Main" (pre-handled above)
    match = re.match(r'^(\d+)\s+(N|S|E|W)?\s*(.*)$', raw_addr)
    
    if match:
        number, predir, street = match.groups()
        predir = predir or ""
        # Strip common suffixes for the API
        suffixes = [" STREET", " ST", " ROAD", " RD", " AVENUE", " AVE", " DRIVE", " DR", " LANE", " LN", " COURT", " CT", " PLACE", " PL"]
        clean_street = street.strip()
        for s in suffixes:
            if clean_street.endswith(s):
                clean_street = clean_street[:len(clean_street)-len(s)]
                break
        street = clean_street
    else:
        parts = raw_addr.split(' ', 1)
        number = parts[0]
        street = parts[1] if len(parts) > 1 else ""
        predir = ""

    params = {
        'number': number,
        'street': street,
        'predir': predir,
        'swis': address_dict['swis']
    }
    
    print(f"Searching for {address_dict['address']} (Num: {number}, Street: {street}, SWIS: {address_dict['swis']})...")
    resp = requests.get(f"{API_BASE_URL}/search_extract_addresses.asp", params=params)
    data = resp.json()
    
    if data.get('success') and data.get('data'):
        return data['data'][0]
    else:
        # Debugging: Try searching without SWIS to see what's available
        print(f"  DEBUG: No exact match. SWIS used: {address_dict['swis']}")
        return None

def get_details(parcel_id, swis):
    """Fetches full physical details for a parcel."""
    params = {
        'parcelid': parcel_id,
        'county': swis[:2],
        'town': swis[2:4],
        'village': swis[4:6]
    }
    resp = requests.get(f"{API_BASE_URL}/get_property_details.asp", params=params)
    return resp.json()

def main():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    core = TaxGrieveCore()

    for comp in COMPS:
        parcel_data = core.search_address(comp['address'].split(' ')[0], ' '.join(comp['address'].split(' ')[1:]), swis=comp['swis'])
        if not parcel_data:
            print(f"  FAILED to find parcel for {comp['address']}")
            continue
        
        # Use simplified enrichment
        official_data = core.get_full_rps_data(parcel_data['parcelgrid'])
        if not official_data:
            print(f"  FAILED to get details for {comp['address']}")
            continue
        
        print(f"  Found: {official_data['sqft']} sqft, {official_data['acreage']} acres, Built {official_data['year_built']}")
        
        # Insert into sales_comps
        cursor.execute("""
            INSERT OR REPLACE INTO sales_comps 
            (address, sbl, sale_price, sale_date, sqft, acreage, bedrooms, bathrooms, year_built, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'MANUAL_ENRICHED')
        """, (
            official_data['address'], official_data['sbl'], comp['sale_price'], comp['sale_date'],
            official_data['sqft'], official_data['acreage'], official_data['bedrooms'], official_data['bathrooms'], 
            official_data['year_built']
        ))
        
        # Throttling to be polite to the API
        time.sleep(0.5)

    conn.commit()
    conn.close()
    print("Database updated successfully.")

if __name__ == "__main__":
    main()
