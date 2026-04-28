from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.core import TaxGrieveCore
import sqlite3

app = FastAPI()
core = TaxGrieveCore()

# Setup templates
templates = Jinja2Templates(directory="src/templates")

@app.get("/", response_class=HTMLResponse)
async def read_item(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

import traceback

@app.post("/report", response_class=HTMLResponse)
async def generate_report(request: Request, address: str = Form(...)):
    try:
        # 1. Parse address (basic)
        address = address.strip()
        parts = address.split(' ', 1)
        if len(parts) < 2:
            return HTMLResponse("Invalid address format. Use 'Number Street'")
        
        number, street = parts
        
        # 2. Search ParcelAccess
        p_data = core.search_address(number, street)
        if not p_data:
            return HTMLResponse(f"""
                <div style="font-family:sans-serif; text-align:center; padding:50px;">
                    <h2>Property Not Found</h2>
                    <p>We couldn't find <b>{address}</b> in the official Dutchess County database.</p>
                    <ul style="display:inline-block; text-align:left;">
                        <li>Check your spelling</li>
                        <li>Try using just the street name (e.g., '67 Parsonage')</li>
                        <li>Make sure the property is in Rhinebeck, Red Hook, or Clinton</li>
                    </ul>
                    <br><br>
                    <a href="/" style="padding:10px 20px; background:#27ae60; color:white; text-decoration:none; border-radius:4px;">Try Again</a>
                </div>
            """)
        
        # 3. Get Full Subject Data
        subject = core.get_full_rps_data(p_data['parcelgrid'])
        if not subject:
            return HTMLResponse(f"Could not retrieve details for: {address}")
        
        # 4. Get Comps from DB
        conn = sqlite3.connect('grievance_data.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Logic: Find most relevant existing set in DB based on SWIS match
        swis = subject['sbl'][:6]
        cursor.execute("""
            SELECT id FROM properties 
            WHERE SUBSTR(sbl, 1, 6) = ? 
            LIMIT 1
        """, (swis,))
        row = cursor.fetchone()
        
        # Fallback to nearest set if SWIS doesn't match
        target_id = row[0] if row else 2 
        
        cursor.execute("SELECT * FROM sales_comps WHERE target_property_id = ?", (target_id,))
        comps = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        if not comps:
            return HTMLResponse(f"No comparable sales found in database for this area.")
        
        # 5. Calculate Valuation
        market_value, adjusted_comps = core.calculate_valuation(subject, comps)
        
        # 6. Recommendation (Use subject's 2025 assessment if 2026 is unknown)
        reduction = max(0, subject['assessment_2025'] - market_value)
        
        return templates.TemplateResponse(
            request=request,
            name="report.html",
            context={
                "subject": subject,
                "comps": adjusted_comps,
                "market_value": market_value,
                "reduction": reduction
            }
        )
    except Exception as e:
        print(f"ERROR: {str(e)}")
        traceback.print_exc()
        return HTMLResponse(f"Internal Server Error: {str(e)}<br><pre>{traceback.format_exc()}</pre>")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
