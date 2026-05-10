import requests
import sqlite3
import time

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
        
        for sale in sales:
            # Normalize address format
            addr = f"{sale['loc_st_nbr'].strip()} {sale['loc_st_name'].strip()} {sale['Loc_mail_st_suff'].strip()}".title()
            
            # Map API fields to our DB fields
            # Note: bathrooms = full + 0.5 * half
            baths = float(sale.get('nbr_full_baths', 0)) + (0.5 * float(sale.get('nbr_half_baths', 0)))
            
            cursor.execute("""
                INSERT OR REPLACE INTO sales_comps 
                (address, sbl, sale_price, sale_date, sqft, acreage, bedrooms, bathrooms, year_built, target_property_id, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'API_DISCOVERY')
            """, (
                addr, sale['parcelgrid'], sale['sale_price'], sale['sale_date'],
                sale['sfla'], sale['acreage'], sale['nbr_bedrooms'], baths,
                sale['yr_built'], subject['id']
            ))
        
        time.sleep(1) # Be kind

    conn.commit()
    conn.close()
    print("Discovery complete. Comps added to database.")

if __name__ == "__main__":
    main()
