import sqlite3

DB_PATH = 'grievance_data.db'

def get_adjustments(cursor):
    cursor.execute("SELECT adj_type, value_per_unit FROM adjustments")
    return {row[0]: row[1] for row in cursor.fetchall()}

def calculate_adjusted_price(subject, comp, adjs):
    adjusted_price = comp['sale_price']
    
    # Square Footage Adjustment
    sqft_diff = subject['sqft'] - comp['sqft']
    gla_adj = sqft_diff * adjs.get('sqft', 0)
    adjusted_price += gla_adj
    
    # Acreage Adjustment
    acre_diff = subject['acreage'] - comp['acreage']
    acreage_adj = acre_diff * adjs.get('acre', 0)
    adjusted_price += acreage_adj
    
    # Bathroom Adjustment
    bath_diff = subject['bathrooms'] - comp['bathrooms']
    bath_adj = bath_diff * adjs.get('bathroom', 0)
    adjusted_price += bath_adj
    
    # Bedroom Adjustment
    bed_diff = subject['bedrooms'] - comp['bedrooms']
    bed_adj = bed_diff * adjs.get('bedroom', 0)
    adjusted_price += bed_adj
    
    # Year Built (Age) Adjustment
    age_diff = subject['year_built'] - comp['year_built']
    age_adj = age_diff * adjs.get('year_built', 0)
    adjusted_price += age_adj
    
    return adjusted_price, {
        "gla": gla_adj,
        "acreage": acreage_adj,
        "bath": bath_adj,
        "bed": bed_adj,
        "age": age_adj
    }

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    adjs = get_adjustments(cursor)
    
    # Process each subject property
    cursor.execute("SELECT * FROM properties")
    subjects = cursor.fetchall()
    
    for subject in subjects:
        print(f"\n--- VALUATION REPORT: {subject['address']} ---")
        print(f"Current Assessment: ${subject['assessed_value_2026'] or subject['assessment_2025']:,.0f}")
        
        # Get comps for this subject
        cursor.execute("SELECT * FROM sales_comps WHERE target_property_id = ?", (subject['id'],))
        comps = cursor.fetchall()
        
        if not comps:
            print("  No comps found.")
            continue
            
        adjusted_prices = []
        for comp in comps:
            adj_price, details = calculate_adjusted_price(subject, comp, adjs)
            adjusted_prices.append(adj_price)
            
            # Update the DB with the reconciled value
            conn.execute("UPDATE sales_comps SET reconciled_value = ? WHERE id = ?", (adj_price, comp['id']))
            
            print(f"  Comp: {comp['address']}")
            print(f"    Sale Price: ${comp['sale_price']:,.0f}")
            print(f"    Adjustments: GLA({details['gla']:+,.0f}), Acre({details['acreage']:+,.0f}), Bath({details['bath']:+,.0f}), Age({details['age']:+,.0f})")
            print(f"    ADJUSTED PRICE: ${adj_price:,.0f}")

        if adjusted_prices:
            market_value = sum(adjusted_prices) / len(adjusted_prices)
            print(f"\n  INDIICATED MARKET VALUE: ${market_value:,.0f}")
            print(f"  POTENTIAL REDUCTION: ${max(0, (subject['assessed_value_2026'] or subject['assessment_2025']) - market_value):,.0f}")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    main()
