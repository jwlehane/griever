import sqlite3

DB_PATH = 'grievance_data.db'

def get_adjustments(cursor):
    cursor.execute("SELECT adj_type, value_per_unit FROM adjustments")
    return {row[0]: row[1] for row in cursor.fetchall()}

def calculate_adjusted_price(subject, comp, adjs):
    adjusted_price = comp['sale_price']
    
    # Helper to handle None
    def get_val(obj, key, default=0):
        val = obj.get(key)
        return val if val is not None else default

    # Square Footage Adjustment
    sqft_diff = get_val(subject, 'sqft') - get_val(comp, 'sqft')
    gla_adj = sqft_diff * adjs.get('sqft', 0)
    adjusted_price += gla_adj
    
    # Acreage Adjustment
    acre_diff = get_val(subject, 'acreage') - get_val(comp, 'acreage')
    acreage_adj = acre_diff * adjs.get('acre', 0)
    adjusted_price += acreage_adj
    
    # Bathroom Adjustment
    bath_diff = get_val(subject, 'bathrooms') - get_val(comp, 'bathrooms')
    bath_adj = bath_diff * adjs.get('bathroom', 0)
    adjusted_price += bath_adj
    
    # Bedroom Adjustment
    bed_diff = get_val(subject, 'bedrooms') - get_val(comp, 'bedrooms')
    bed_adj = bed_diff * adjs.get('bedroom', 0)
    adjusted_price += bed_adj
    
    # Year Built (Age) Adjustment
    age_diff = get_val(subject, 'year_built') - get_val(comp, 'year_built')
    age_adj = age_diff * adjs.get('year_built', 0)
    adjusted_price += age_adj
    
    return adjusted_price, {
        "gla": gla_adj,
        "acreage": acreage_adj,
        "bath": bath_adj,
        "bed": bed_adj,
        "age": age_adj
    }

def detect_outliers(reconciled_prices, threshold=0.25):
    """
    Identifies outliers based on deviation from the mean reconciled price.
    """
    if not reconciled_prices: return []
    mean = sum(reconciled_prices) / len(reconciled_prices)
    outliers = []
    for price in reconciled_prices:
        deviation = abs(price - mean) / mean
        outliers.append(deviation > threshold)
    return outliers

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    adjs = get_adjustments(cursor)
    
    # Process each subject property
    cursor.execute("SELECT * FROM properties")
    subjects = cursor.fetchall()
    
    for subject_row in subjects:
        subject = dict(subject_row)
        print(f"\n--- VALUATION REPORT: {subject['address']} ---")
        current_assessment = subject['assessed_value_2026'] or subject['assessment_2025']
        print(f"Current Assessment: ${current_assessment:,.0f}")
        
        # Get comps for this subject
        cursor.execute("SELECT * FROM sales_comps WHERE target_property_id = ?", (subject['id'],))
        comps = [dict(row) for row in cursor.fetchall()]
        
        if not comps:
            print("  No comps found.")
            continue
            
        adjusted_data = []
        for comp in comps:
            adj_price, details = calculate_adjusted_price(subject, comp, adjs)
            adjusted_data.append({'price': adj_price, 'comp_id': comp['id'], 'details': details, 'address': comp['address'], 'sale_price': comp['sale_price']})
            
            # Update the DB with the reconciled value
            conn.execute("UPDATE sales_comps SET reconciled_value = ? WHERE id = ?", (adj_price, comp['id']))

        # Outlier Detection
        prices = [d['price'] for d in adjusted_data]
        is_outlier = detect_outliers(prices)
        
        final_valid_prices = []
        for i, d in enumerate(adjusted_data):
            d['is_outlier'] = is_outlier[i]
            conn.execute("UPDATE sales_comps SET is_outlier = ? WHERE id = ?", (1 if d['is_outlier'] else 0, d['comp_id']))
            
            status = " [OUTLIER]" if d['is_outlier'] else ""
            print(f"  Comp: {d['address']}{status}")
            print(f"    Sale Price: ${d['sale_price']:,.0f}")
            print(f"    Adjustments: GLA({d['details']['gla']:+,.0f}), Acre({d['details']['acreage']:+,.0f}), Bath({d['details']['bath']:+,.0f}), Age({d['details']['age']:+,.0f})")
            print(f"    ADJUSTED PRICE: ${d['price']:,.0f}")
            
            if not d['is_outlier']:
                final_valid_prices.append(d['price'])

        if final_valid_prices:
            market_value = sum(final_valid_prices) / len(final_valid_prices)
            print(f"\n  INDICATED MARKET VALUE (Excl. Outliers): ${market_value:,.0f}")
            print(f"  POTENTIAL REDUCTION: ${max(0, current_assessment - market_value):,.0f}")
        elif adjusted_data:
            print("\n  WARNING: All comps identified as outliers. Manual review required.")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    main()
