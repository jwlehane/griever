import sqlite3
import random

DB_PATH = 'grievance_data.db'

def generate_test_data():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Clear existing if user wants or just add
    # cursor.execute("DELETE FROM sales_comps")
    # cursor.execute("DELETE FROM properties")
    
    # 1. Subject Property
    subject = {
        'address': 'Test Subject 1',
        'sbl': f'TEST-{random.randint(1000, 9999)}',
        'sqft': 2000,
        'bedrooms': 3,
        'bathrooms': 2,
        'acreage': 1.0,
        'year_built': 1980,
        'assessment_2025': 500000
    }
    
    cursor.execute("""
        INSERT OR REPLACE INTO properties 
        (address, sbl, sqft, bedrooms, bathrooms, acreage, year_built, assessment_2025)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (subject['address'], subject['sbl'], subject['sqft'], subject['bedrooms'], subject['bathrooms'], subject['acreage'], subject['year_built'], subject['assessment_2025']))
    
    prop_id = cursor.lastrowid
    
    # 2. Generage 5 Comps
    for i in range(5):
        # Varying levels of similarity
        sqft_var = random.uniform(0.8, 1.2)
        price_base = 500000 * sqft_var
        
        comp = {
            'address': f'Test Comp {i}',
            'sbl': f'COMP-{random.randint(1000, 9999)}',
            'sale_price': price_base * random.uniform(0.9, 1.1),
            'sqft': subject['sqft'] * sqft_var,
            'year_built': subject['year_built'] + random.randint(-20, 20),
            'acreage': subject['acreage'] * random.uniform(0.7, 1.3),
            'distance_miles': random.uniform(0.1, 3.0)
        }
        
        # Insert one outlier
        if i == 4:
            comp['sale_price'] *= 2.0
            
        cursor.execute("""
            INSERT OR REPLACE INTO sales_comps 
            (address, sbl, sale_price, sale_date, sqft, acreage, year_built, distance_miles, target_property_id, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (comp['address'], comp['sbl'], comp['sale_price'], '2025-01-01', comp['sqft'], comp['acreage'], comp['year_built'], comp['distance_miles'], prop_id, 'TEST_GEN'))

    conn.commit()
    conn.close()
    print(f"Generated test property (ID: {prop_id}) and 5 comps (1 intentional outlier).")

if __name__ == "__main__":
    generate_test_data()
