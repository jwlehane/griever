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

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    core = TaxGrieveCore()

    cursor.execute("SELECT * FROM properties")
    subjects = cursor.fetchall()

    for subject in subjects:
        print(f"Discovering comps for {subject['address']} using RapidAPI...")
        
        # Use the robust live discovery method
        all_comps = []
        for update in core.discover_comps_live(dict(subject)):
            if update['status'] == 'complete':
                all_comps = update['comps']
            elif update['status'] == 'verified':
                print(f"  ✅ Verified: {update['comp']['address']}")
            elif update['status'] == 'error':
                print(f"  ❌ Error: {update['message']}")

        print(f"  Found and verified {len(all_comps)} potential comps.")
        
        for comp in all_comps:
            score = core.calculate_similarity(dict(subject), comp)
            
            cursor.execute("""
                INSERT OR REPLACE INTO sales_comps 
                (address, sbl, sale_price, sale_date, sqft, acreage, bedrooms, bathrooms, year_built, target_property_id, source, similarity_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'API_DISCOVERY', ?)
            """, (
                comp['address'], comp['sbl'], comp['sale_price'], comp['sale_date'],
                comp['sqft'], comp['acreage'], comp['bedrooms'], comp['bathrooms'],
                comp['year_built'], subject['id'], score
            ))
        
        time.sleep(1) # Be kind

    conn.commit()
    conn.close()
    print("Discovery complete. Comps added to database.")

if __name__ == "__main__":
    main()
