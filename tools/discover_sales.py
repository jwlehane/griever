import requests
import sqlite3
import time
import sys
import os

# Add src to path for core logic
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))
from app.core import TaxGrieveCore

DB_PATH = 'grievance_data.db'
API_BASE_URL = "https://gis.dutchessny.gov/parcelaccess/asp"

def discover_sales(session, subject, min_sale_date="01/01/2024"):
    """
    Queries the County API for sales similar to the subject property.
    """
    # Define a 'Comparable Range'
    min_sqft = int(subject['sqft'] * 0.80)
    max_sqft = int(subject['sqft'] * 1.20)
    
    # County API expects MM/DD/YYYY
    from datetime import datetime
    max_date = datetime.now().strftime("%m/%d/%Y")
    
    params = {
        "swis": subject['sbl'][:6],
        "minSaleDate": min_sale_date,
        "maxSaleDate": max_date,
        "propClass": "210", 
        "minSfla": min_sqft,
        "maxSfla": max_sqft,
        "minAcreage": max(0, round(subject['acreage'] - 1.0, 2)),
        "maxAcreage": round(subject['acreage'] + 1.0, 2),
        "minYrBuilt": 1650,
        "maxYrBuilt": 2026,
        "bldgStyle": "",
        "nbrBedrooms": ""
    }

    print(f"Querying sales for {subject['address']} (Range: {min_sqft}-{max_sqft} sqft)...")
    
    # The server requires a Referer and a Session
    headers = {
        "Referer": "https://gis.dutchessny.gov/parcelaccess/",
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    resp = session.post(f"{API_BASE_URL}/search_residential_sales.asp", data=params, headers=headers)
    print(f"DEBUG: Status {resp.status_code}, Body: {resp.text[:200]}")
    
    try:
        data = resp.json()
        if data.get('success'):
            return data['data']
    except Exception as e:
        print(f"  API Error: {resp.status_code} - {resp.text[:100]}")
    
    return []

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Initialize Session
    session = requests.Session()
    session.get("https://gis.dutchessny.gov/parcelaccess/") # Get cookies

    cursor.execute("SELECT * FROM properties")
    subjects = cursor.fetchall()

    for subject in subjects:
        sales = discover_sales(session, subject)
        print(f"  Found {len(sales)} potential comps for {subject['address']}.")
        
        # Prepare for scoring
        core = TaxGrieveCore()
        scored_sales = []

        for sale in sales:
            # Map API fields to our format for scoring
            baths = float(sale.get('nbr_full_baths', 0)) + (0.5 * float(sale.get('nbr_half_baths', 0)))
            comp_data = {
                'sqft': sale.get('sfla', 0),
                'year_built': sale.get('yr_built', 0),
                'acreage': sale.get('acreage', 0),
                'distance_miles': 0.5 # Placeholder for now
            }
            score = core.calculate_similarity(dict(subject), comp_data)
            
            # Normalize address
            addr = f"{sale['loc_st_nbr'].strip()} {sale['loc_st_name'].strip()} {sale['Loc_mail_st_suff'].strip()}".title()
            
            scored_sales.append({
                'data': sale,
                'address': addr,
                'bathrooms': baths,
                'score': score
            })

        # Sort by similarity score descending
        scored_sales.sort(key=lambda x: x['score'], reverse=True)

        for item in scored_sales:
            sale = item['data']
            cursor.execute("""
                INSERT OR REPLACE INTO sales_comps 
                (address, sbl, sale_price, sale_date, sqft, acreage, bedrooms, bathrooms, year_built, target_property_id, source, similarity_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'API_DISCOVERY', ?)
            """, (
                item['address'], sale['parcelgrid'], sale['sale_price'], sale['sale_date'],
                sale['sfla'], sale['acreage'], sale['nbr_bedrooms'], item['bathrooms'],
                sale['yr_built'], subject['id'], item['score']
            ))
        
        time.sleep(1) # Be kind

    conn.commit()
    conn.close()
    print("Discovery complete. Comps added to database.")

if __name__ == "__main__":
    main()
