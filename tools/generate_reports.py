import sqlite3
import os

DB_PATH = 'grievance_data.db'

def get_report_data(cursor, property_id):
    # Get subject info
    cursor.execute("SELECT * FROM properties WHERE id = ?", (property_id,))
    subject = cursor.fetchone()
    
    # Get comps
    cursor.execute("SELECT * FROM sales_comps WHERE target_property_id = ?", (property_id,))
    comps = cursor.fetchall()
    
    return subject, comps

def generate_narrative(subject, market_value):
    current_val = subject['assessed_value_2026'] or subject['assessment_2025']
    reduction = current_val - market_value
    
    narrative = f"""
    The subject property located at {subject['address']} is currently assessed at ${current_val:,.0f}. 
    Based on a review of {subject['sqft']:,.0f} sq. ft. comparable residential sales in the immediate market area, 
    the indicated market value is approximately ${market_value:,.0f}. 
    
    Adjustments were made for differences in square footage, acreage, and utility (bathrooms/age) to arrive at this figure. 
    The current assessment represents an over-valuation of approximately { (reduction/current_val)*100:.1f}%. 
    I respectfully request that the assessment be reduced to ${market_value:,.0f} to align with the fair market value 
    demonstrated by recent arm's length transactions of similar properties.
    """
    return narrative.strip()

def main():
    if not os.path.exists(DB_PATH):
        print("Database not found.")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT id, address FROM properties")
    subjects = cursor.fetchall()

    for sub_row in subjects:
        subject, comps = get_report_data(cursor, sub_row['id'])
        if not comps: continue

        # Calculate average of reconciled values
        reconciled_values = [c['reconciled_value'] for c in comps if c['reconciled_value']]
        if not reconciled_values: continue
        
        market_value = sum(reconciled_values) / len(reconciled_values)
        
        # Suggestion Logic: Identify Outliers
        avg = market_value
        outliers = [c for c in comps if c['reconciled_value'] and abs(c['reconciled_value'] - avg) / avg > 0.25]
        
        report_path = f"reports/grievance_report_{sub_row['id']}.md"
        os.makedirs("reports", exist_ok=True)
        
        with open(report_path, "w") as f:
            f.write(f"# Property Tax Grievance Report\n")
            f.write(f"**Subject Property:** {subject['address']}\n")
            f.write(f"**Current Assessment (2026):** ${subject['assessed_value_2026'] or subject['assessment_2025']:,.0f}\n\n")
            
            f.write(f"## 1. Valuation Summary\n")
            f.write(f"Based on the analysis of {len(comps)} comparable sales, the adjusted market value is:\n")
            f.write(f"### **Indicated Market Value: ${market_value:,.0f}**\n")
            f.write(f"**Target Reduction:** ${ (subject['assessed_value_2026'] or subject['assessment_2025']) - market_value:,.0f}\n\n")
            
            f.write(f"## 2. Suggestion Engine Analysis\n")
            if outliers:
                for o in outliers:
                    direction = "high" if o['reconciled_value'] > avg else "low"
                    f.write(f"- ⚠️ **Outlier Detected:** {o['address']} is significantly {direction} (${o['reconciled_value']:,.0f}). Removing this could {'strengthen' if direction == 'high' else 'weaken'} your case.\n")
            else:
                f.write(f"- ✅ **Comp Set Strength:** The comps are tightly clustered, providing a strong basis for the valuation.\n")
            
            f.write(f"\n## 3. Comparable Sales Table (Adjusted)\n")
            f.write(f"| Address | Sale Price | SqFt | Adjusted Value |\n")
            f.write(f"| :--- | :--- | :--- | :--- |\n")
            for c in comps:
                f.write(f"| {c['address']} | ${c['sale_price']:,.0f} | {c['sqft']:,.0f} | ${c['reconciled_value']:,.0f} |\n")
            
            f.write(f"\n## 4. Grievance Narrative (For Form RP-524)\n")
            f.write(f"> {generate_narrative(subject, market_value)}\n")

        print(f"Report generated: {report_path}")

    conn.close()

if __name__ == "__main__":
    main()
