import sqlite3

DB_PATH = 'grievance_data.db'

def main():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Subject Property Data (Already extracted)
    subject = {
        "address": "67 N Parsonage St",
        "sbl": "13500100617000156384180000",
        "sqft": 2580,
        "acreage": 0.43,
        "bedrooms": 4,
        "bathrooms": 2.5,
        "year_built": 2006,
        "assessment_2025": 948300,
        "assessment_2026": 986200
    }

    cursor.execute("""
        INSERT OR REPLACE INTO properties 
        (address, sbl, sqft, acreage, bedrooms, bathrooms, year_built, assessed_value_2026)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        subject['address'], subject['sbl'], subject['sqft'], subject['acreage'],
        subject['bedrooms'], subject['bathrooms'], subject['year_built'], subject['assessment_2026']
    ))

    conn.commit()
    conn.close()
    print("Subject property data inserted.")

if __name__ == "__main__":
    main()
