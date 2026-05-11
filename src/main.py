from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.core import TaxGrieveCore
from app.utils import send_error_report
from app.counties.factory import CountyFactory
import sqlite3
import traceback
import json
from fastapi.responses import StreamingResponse
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()
core = TaxGrieveCore()

# Setup templates
templates = Jinja2Templates(directory="src/templates")

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # Log and send report for any unhandled exceptions
    send_error_report(exc, {"path": request.url.path, "method": request.method})
    return HTMLResponse(
        content="""
        <div style="font-family:sans-serif; text-align:center; padding:50px;">
            <h2>System Unavailable</h2>
            <p>The County system is currently experiencing high load or is unavailable.</p>
            <p>We have reported this issue to our developers. Please try again later.</p>
            <br>
            <button onclick="window.history.back()" style="padding:10px 20px; background:#34495e; color:white; border:none; border-radius:4px; cursor:pointer;">Back</button>
        </div>
        """,
        status_code=500
    )

@app.get("/", response_class=HTMLResponse)
async def read_item(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

@app.post("/search_property")
async def search_property(request: Request, address: str = Form(...)):
    try:
        subject = core.get_subject_profile(address.strip())
        if not subject:
            return {"status": "error", "message": f"Property not found: {address}"}
        
        subject_id = core.ensure_property(subject)
        # Add town info for UI
        county = CountyFactory.get_county_handler(subject['address'])
        subject['town'] = county.get_town_from_identifier(subject['sbl'])
        
        return {
            "status": "success",
            "subject": subject,
            "subject_id": subject_id
        }
    except Exception as e:
        send_error_report(e, {"address": address, "phase": "search_property"})
        return {"status": "error", "message": str(e)}

@app.post("/report")
async def generate_report(request: Request, address: str = Form(...), subject_id: int = Form(None), renovation_year: int = Form(None), skip_discovery: bool = Form(False)):
    # Capture outer scope values for the closure
    init_subject_id = subject_id
    init_address = address
    init_renov = renovation_year
    init_skip = skip_discovery

    async def event_generator():
        # Use a local subject_id variable to avoid UnboundLocalError
        active_subject_id = init_subject_id
        
        try:
            # Safety: If active_subject_id is missing but address is present, re-identify
            if not active_subject_id and init_address:
                subject_profile = core.get_subject_profile(init_address.strip())
                if subject_profile:
                    active_subject_id = core.ensure_property(subject_profile)
            
            if not active_subject_id:
                yield f"data: {json.dumps({'status': 'error', 'message': 'Property session lost. Please search again.'})}\n\n"
                return

            # Fetch subject from DB
            conn = sqlite3.connect('grievance_data.db')
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM properties WHERE id = ?", (active_subject_id,))
            row = cursor.fetchone()
            if not row:
                yield f"data: {json.dumps({'status': 'error', 'message': 'Property not found in database.'})}\n\n"
                return
            subject = dict(row)
            conn.close()

            if not init_skip:
                subject_name = subject["address"]
                info_payload = json.dumps({'status': 'info', 'message': f'Starting discovery for {subject_name}...', 'subject_id': active_subject_id})
                yield f"data: {info_payload}\n\n"
                
                # 2. Start Live Discovery Generator
                all_live_comps = []
                # Run the generator in a way that doesn't block the event loop
                def get_updates():
                    return list(core.discover_comps_live(subject, active_subject_id))

                # Since discover_comps_live is a generator, we iterate through it
                # We'll keep it simple for now but use a shorter sleep
                for update in core.discover_comps_live(subject, active_subject_id):
                    if update['status'] == 'complete':
                        all_live_comps = update['comps']
                    else:
                        yield f"data: {json.dumps(update)}\n\n"
                    await asyncio.sleep(0.001)

            else:
                yield f"data: {json.dumps({'status': 'info', 'message': 'Generating report from existing comps...'})}\n\n"

            # 3. Finalize
            conn = sqlite3.connect('grievance_data.db')
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sales_comps WHERE target_property_id = ? AND status != 'REJECTED'", (active_subject_id,))
            comps = [dict(row) for row in cursor.fetchall()]
            conn.close()

            if not comps:
                yield f"data: {json.dumps({'status': 'no_comps', 'message': 'No matching sales found.', 'subject_id': active_subject_id})}\n\n"
                return

            # 4. Calculate Valuation
            market_value, adjusted_comps = core.calculate_valuation(subject, comps, renovation_year=init_renov)
            
            # Defensive check for assessment values
            subj_ass_25 = subject.get('assessment_2025')
            if subj_ass_25 is None: subj_ass_25 = subject.get('assessment_2026', 0)
            if subj_ass_25 is None: subj_ass_25 = 0
            
            reduction = max(0, float(subj_ass_25) - float(market_value))
            
            # 5. Render final HTML
            html_content = templates.get_template("report.html").render({
                "request": request,
                "subject": subject,
                "subject_id": active_subject_id,
                "comps": [c for c in adjusted_comps if c.get('status') != 'REJECTED'],
                "market_value": market_value,
                "reduction": reduction,
                "renovation_year": init_renov
            })
            
            yield f"data: {json.dumps({'status': 'finished', 'html': html_content})}\n\n"

        except Exception as e:
            import traceback
            traceback.print_exc()
            error_ctx = {
                "subject_id": active_subject_id, 
                "phase": "streaming_report",
                "subject_data": str(subject) if 'subject' in locals() else "Not loaded"
            }
            send_error_report(e, error_ctx)
            yield f"data: {json.dumps({'status': 'error', 'message': f'Internal error: {str(e)}'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/add_comp")
async def add_comp(request: Request, property_id: int = Form(...), address: str = Form(...), price: float = Form(...)):
    success = core.add_manual_comp(property_id, address, price)
    if success:
        return HTMLResponse(f"""
            <div style="font-family:sans-serif; text-align:center; padding:50px;">
                <h2>Comp Added!</h2>
                <p>We've verified and added {{address}} to your property record.</p>
                <br>
                <form action="/report" method="post">
                    <input type="hidden" name="address" value="RESUME">
                    <button type="submit" style="padding:10px 20px; background:#27ae60; color:white; border:none; border-radius:4px; cursor:pointer;">Show Report</button>
                </form>
            </div>
        """)
    else:
        return HTMLResponse("Failed to verify address on County API. Check spelling.")

@app.post("/reject_comp")
async def reject_comp(request: Request, property_id: int = Form(...), address: str = Form(...), zpid: str = Form(None)):
    conn = sqlite3.connect('grievance_data.db')
    cursor = conn.cursor()
    if zpid:
        cursor.execute("UPDATE sales_comps SET status = 'REJECTED' WHERE target_property_id = ? AND zpid = ?", (property_id, zpid))
    else:
        cursor.execute("UPDATE sales_comps SET status = 'REJECTED' WHERE target_property_id = ? AND address = ?", (property_id, address))
    conn.commit()
    conn.close()
    return HTMLResponse("""
        <div style="font-family:sans-serif; text-align:center; padding:50px;">
            <h2>Comp Rejected</h2>
            <p>This sale will no longer be used in your valuation calculations.</p>
            <button onclick="window.history.back()" style="padding:10px 20px; background:#34495e; color:white; border:none; border-radius:4px; cursor:pointer;">Back</button>
        </div>
    """)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
