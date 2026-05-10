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

import json
from fastapi.responses import StreamingResponse
import asyncio

@app.post("/report")
async def generate_report(request: Request, address: str = Form(...)):
    async def event_generator():
        try:
            # 1. Parse address
            address_clean = address.strip()
            parts = address_clean.split(' ', 1)
            if len(parts) < 2:
                yield f"data: {json.dumps({'status': 'error', 'message': 'Invalid address format'})}\n\n"
                return
            
            number, street = parts
            
            # 2. Search ParcelAccess
            yield f"data: {json.dumps({'status': 'searching', 'message': f'Locating {address_clean} in County Database...'})}\n\n"
            p_data = core.search_address(number, street)
            if not p_data:
                yield f"data: {json.dumps({'status': 'error', 'message': f'Property not found: {address_clean}'})}\n\n"
                return
            
            # 3. Get Full Subject Data
            subject = core.get_full_rps_data(p_data['parcelgrid'])
            subject_id = core.ensure_property(subject) # Save and get ID
            yield f"data: {json.dumps({'status': 'info', 'message': f'Verified Subject: {subject[\"address\"]} ({subject[\"sqft\"]:,} sqft)'})}\n\n"
            
            # 4. Start Live Discovery Generator
            all_live_comps = []
            for update in core.discover_comps_live(subject):
                if update['status'] == 'complete':
                    all_live_comps = update['comps']
                elif update['status'] == 'verified':
                    yield f"data: {json.dumps({'status': 'update', 'message': f'✅ Verified: {update[\"comp\"][\"address\"]}'})}\n\n"
                else:
                    yield f"data: {json.dumps(update)}\n\n"
                await asyncio.sleep(0.1)

            # 5. Finalize with Fallback if needed
            comps = all_live_comps
            if not comps:
                # Check if we have manual/curated comps in DB first
                conn = sqlite3.connect('grievance_data.db')
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM sales_comps WHERE target_property_id = ?", (subject_id,))
                comps = [dict(row) for row in cursor.fetchall()]
                conn.close()

                if not comps:
                    yield f"data: {json.dumps({'status': 'no_comps', 'message': 'No matching sales found.', 'subject_id': subject_id})}\n\n"
                    return

            # 6. Calculate Valuation
            market_value, adjusted_comps = core.calculate_valuation(subject, comps)
            reduction = max(0, subject['assessment_2025'] - market_value)
            
            # 7. Render final HTML
            html_content = templates.get_template("report.html").render({
                "request": request,
                "subject": subject,
                "subject_id": subject_id,
                "comps": adjusted_comps,
                "market_value": market_value,
                "reduction": reduction
            })
            
            yield f"data: {json.dumps({'status': 'finished', 'html': html_content})}\n\n"

        except Exception as e:
            traceback.print_exc()
            yield f"data: {json.dumps({'status': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/add_comp")
async def add_comp(request: Request, property_id: int = Form(...), address: str = Form(...), price: float = Form(...)):
    success = core.add_manual_comp(property_id, address, price)
    if success:
        return HTMLResponse("""
            <div style="font-family:sans-serif; text-align:center; padding:50px;">
                <h2>Comp Added Successfully!</h2>
                <p>We've verified and added this comp to your property record.</p>
                <br>
                <form action="/report" method="post">
                    <input type="hidden" name="address" value="RE-RUN"> <!-- Frontend handles this -->
                    <button type="button" onclick="window.history.go(-2)" style="padding:10px 20px; background:#27ae60; color:white; border:none; border-radius:4px; cursor:pointer;">Back to Property</button>
                </form>
                <p style="font-size: 12px; color: #666; margin-top:20px;">(Refresh your original search to see the updated report)</p>
            </div>
        """)
    else:
        return HTMLResponse("Failed to verify address on County API. Check spelling.")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
