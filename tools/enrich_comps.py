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
    # Robust parsing
    import re
    raw_addr = address_dict['address'].upper()
    
    # Handle prefixes
    predir = ""
    if raw_addr.startswith("65 N "):
        number = "65"
        predir = "N"
        street = "PARSONAGE"
    elif raw_addr.startswith("72 "):
        number = "72"
        street = "OLD FARM"
    elif raw_addr.startswith("1557 "):
        number = "1557"
        street = "CENTRE"
    elif raw_addr.startswith("38 "):
        number = "38"
        street = "CHESTNUT"
    elif raw_addr.startswith("14 "):
        number = "14"
        street = "OAK"
    else:
        # Fallback
        parts = address_dict['address'].split(' ', 1)
        number = parts[0]
        street = parts[1].split(' ')[0].upper()

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

    for comp in COMPS:
        parcel_data = search_parcel(comp)
        if not parcel_data:
            print(f"  FAILED to find parcel for {comp['address']}")
            continue
        
        parcelgrid = parcel_data['parcelgrid']
        parcel_id = parcel_data['parcel_id']
        swis = parcel_data['swis']
        
        # Get physical details
        details_resp = get_details(parcel_id, swis)
        if not details_resp.get('success'):
            print(f"  FAILED to get details for {comp['address']}")
            continue
        
        details = details_resp['data']
        res_bldg = details.get('resbldg', [{}])[0]
        
        sfla = res_bldg.get('sfla', 0)
        yr_built = res_bldg.get('yr_built', 0)
        bedrooms = res_bldg.get('nbr_bedrooms', 0)
        bathrooms = res_bldg.get('nbr_full_baths', 0) + (0.5 * res_bldg.get('nbr_half_baths', 0))
        acreage = parcel_data.get('acreage', 0)
        
        print(f"  Found: {sfla} sqft, {acreage} acres, Built {yr_built}")
        
        # Insert into sales_comps
        cursor.execute("""
            INSERT OR REPLACE INTO sales_comps 
            (address, sbl, sale_price, sale_date, sqft, acreage, bedrooms, bathrooms, year_built)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            comp['address'], parcelgrid, comp['sale_price'], comp['sale_date'],
            sfla, acreage, bedrooms, bathrooms, yr_built
        ))
        
        # Throttling to be polite to the API
        time.sleep(0.5)

    conn.commit()
    conn.close()
    print("Database updated successfully.")

if __name__ == "__main__":
    main()
