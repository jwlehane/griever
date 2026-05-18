from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.core import TaxGrieveCore
from app.utils import send_error_report
from app.counties.factory import CountyFactory
from app.db import get_connection
import traceback
import json
import re
import requests
from fastapi.responses import StreamingResponse
import asyncio
import os
from dotenv import load_dotenv

NYS_PARCELS_URL = "https://gisservices.its.ny.gov/arcgis/rest/services/NYS_Tax_Parcels_Public/MapServer/1/query"
CENSUS_GEOCODER_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
AUTOCOMPLETE_COUNTIES = ("Dutchess", "Ulster")

# ZIP → county for service-area filtering of Census Geocoder results.
_DUTCHESS_ZIPS = {
    "12501","12504","12507","12508","12510","12512","12514","12522","12524",
    "12527","12531","12533","12537","12538","12540","12545","12546","12564",
    "12567","12569","12570","12571","12572","12574","12578","12580","12581",
    "12582","12583","12585","12590","12592","12594",
    "12601","12602","12603","12604",
}
_ULSTER_ZIPS_AC = {
    "12401","12404","12409","12410","12411","12412","12416","12419","12420",
    "12428","12429","12432","12433","12435","12440","12443","12446","12449",
    "12453","12456","12457","12458","12461","12464","12465","12466","12471",
    "12472","12474","12477","12480","12481","12483","12484","12486","12487",
    "12489","12491","12493","12494","12495","12498","12515","12525","12528",
    "12547","12548","12548","12549","12561","12566","12575","12589",
}

# Tiny LRU-style cache for autocomplete queries.
_AC_CACHE: dict = {}
_AC_CACHE_MAX = 512

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


def _county_for_zip(zip5: str) -> str:
    if zip5 in _ULSTER_ZIPS_AC:
        return "Ulster"
    if zip5 in _DUTCHESS_ZIPS:
        return "Dutchess"
    return ""


@app.get("/autocomplete")
async def autocomplete(q: str = ""):
    """Address suggestions for Dutchess + Ulster.

    Backed by the US Census Geocoder (fast, ~200ms). Filters results to ZIP
    codes within Dutchess or Ulster County. Triggers once the user has typed
    a house number + at least 3 street chars.
    """
    q = (q or "").strip()
    m = re.match(r"^\s*(\d+)\s+(\S.{2,})$", q)
    if not m:
        return JSONResponse({"suggestions": []})

    cache_key = q.upper()
    if cache_key in _AC_CACHE:
        return JSONResponse({"suggestions": _AC_CACHE[cache_key]})

    address_query = q if re.search(r"\bNY\b", q, re.IGNORECASE) else f"{q}, NY"
    try:
        resp = requests.get(
            CENSUS_GEOCODER_URL,
            params={"address": address_query, "benchmark": "Public_AR_Current", "format": "json"},
            timeout=6,
        )
        resp.raise_for_status()
        matches = resp.json().get("result", {}).get("addressMatches", []) or []
    except Exception as e:
        print(f"autocomplete error: {e}")
        return JSONResponse({"suggestions": [], "error": str(e)})

    suggestions = []
    seen = set()
    for mm in matches:
        comp = mm.get("addressComponents", {}) or {}
        state = (comp.get("state") or "").upper()
        zipc = (comp.get("zip") or "").strip()[:5]
        if state != "NY" or not zipc:
            continue
        county = _county_for_zip(zipc)
        if not county:
            continue
        matched = (mm.get("matchedAddress") or "").strip()
        parts = [p.strip() for p in matched.split(",")]
        if len(parts) < 2:
            continue
        street = parts[0].title()
        city = (comp.get("city") or parts[1]).strip().title()
        key = (street.upper(), zipc)
        if key in seen:
            continue
        seen.add(key)
        suggestions.append({
            "label": matched.title(),
            "value": f"{street}, {city}",
            "address": street,
            "town": city,
            "county": county,
            "zip": zipc,
        })
        if len(suggestions) >= 8:
            break

    if len(_AC_CACHE) >= _AC_CACHE_MAX:
        _AC_CACHE.pop(next(iter(_AC_CACHE)))
    _AC_CACHE[cache_key] = suggestions
    return JSONResponse({"suggestions": suggestions})

@app.post("/search_property")
async def search_property(request: Request, address: str = Form(...)):
    try:
        subject = core.get_subject_profile(address.strip())
        if not subject:
            return {"status": "error", "message": f"Property not found: {address}"}
        
        subject_id = core.ensure_property(subject)
        # SBL-based routing is authoritative — it embeds the SWIS code which
        # tells us the actual county regardless of what was typed.
        county = CountyFactory.get_county_handler(address_string=address, sbl=subject.get('sbl'))
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
async def generate_report(
    request: Request,
    address: str = Form(...),
    subject_id: int = Form(None),
    renovation_year: int = Form(None),
    skip_discovery: bool = Form(False),
    finalize: bool = Form(False), 
    condition: str = Form("average"),
    force_verify: bool = Form(False),
    update_curation: bool = Form(False),
):
    init_subject_id = subject_id
    init_address = address
    init_renov = renovation_year
    init_skip = skip_discovery
    init_finalize = finalize
    init_condition = condition
    init_force = force_verify
    init_update_curation = update_curation

    # --- DIRECT HTML RESPONSE (FINALIZATION PHASE) ---
    if init_finalize or init_update_curation:
        try:
            active_subject_id = init_subject_id
            if not active_subject_id and init_address:
                subject_profile = core.get_subject_profile(init_address.strip())
                if subject_profile:
                    active_subject_id = core.ensure_property(subject_profile)
                    
            if not active_subject_id:
                return HTMLResponse("Property session lost. Please search again.", status_code=400)

            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM properties WHERE id = ?", (active_subject_id,))
            row = cursor.fetchone()
            if not row:
                conn.close()
                return HTMLResponse("Property not found in database.", status_code=404)
            subject = dict(row)
            
            cursor.execute("SELECT * FROM sales_comps WHERE target_property_id = ? AND status != 'REJECTED'" + (" AND is_selected = 1" if init_finalize else ""), (active_subject_id,))
            comps = [dict(r) for r in cursor.fetchall()]
            conn.close()

            if not comps:
                return HTMLResponse("No comps found or selected.", status_code=400)

            condition_factors = {"below": 0.85, "average": 1.00, "above": 1.10, "renovated": 1.20}
            condition_factor = condition_factors.get((init_condition or "average").lower(), 1.0)

            valuation = core.calculate_valuation(
                subject, comps,
                renovation_year=init_renov,
                condition_factor=condition_factor,
                enforce_selection=init_finalize
            )
            
            if init_update_curation:
                sorted_comps = sorted([c for c in valuation["comps"] if c.get('status') != 'REJECTED'], key=lambda x: x.get('similarity_score', 0), reverse=True)
                html_content = templates.get_template("curation.html").render({
                    "request": request,
                    "subject": subject,
                    "subject_id": active_subject_id,
                    "comps": sorted_comps,
                    "renovation_year": init_renov,
                    "condition": init_condition,
                })
                return HTMLResponse(html_content)

            from app.equalization import get_rate as _er_rate, implied_market_value
            er = _er_rate(subject.get('sbl')) 
            current_av = subject.get('assessment_2026') or subject.get('assessment_2025') or 0
            implied_mv = implied_market_value(current_av, subject.get('sbl')) if current_av else None

            if implied_mv:
                reduction_full = max(0.0, float(implied_mv) - float(valuation["market_value"]))
                reduction_av = reduction_full * (er / 100.0) if er else reduction_full
            else:
                reduction_full = max(0.0, float(current_av) - float(valuation["market_value"]))
                reduction_av = reduction_full

            html_content = templates.get_template("report.html").render({
                "request": request,
                "subject": subject,
                "subject_id": active_subject_id,
                "comps": [c for c in valuation["comps"] if c.get('status') != 'REJECTED'],
                "market_value": valuation["market_value"],
                "range_low": valuation["range_low"],
                "range_high": valuation["range_high"],
                "reduction": reduction_av,
                "reduction_full": reduction_full,
                "renovation_year": init_renov,
                "current_av": current_av,
                "equalization_rate": er,
                "implied_market_value": implied_mv,
                "used_count": valuation["used_count"],
                "considered_count": valuation["considered_count"],
                "adjustments_used": valuation["adjustments_used"],
                "condition": init_condition,
            })
            return HTMLResponse(html_content)
        except Exception as e:
            traceback.print_exc()
            return HTMLResponse(f"System error: {str(e)}", status_code=500)

    # --- STREAMING RESPONSE (DISCOVERY & CURATION PHASE) ---
    async def event_generator():
        active_subject_id = init_subject_id
        try:
            if not active_subject_id and init_address:
                subject_profile = core.get_subject_profile(init_address.strip())
                if subject_profile:
                    active_subject_id = core.ensure_property(subject_profile)
            
            if not active_subject_id:
                yield f"data: {json.dumps({'status': 'error', 'message': 'Property session lost. Please search again.'})}\n\n"
                return

            conn = get_connection()
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
                yield f"data: {json.dumps({'status': 'info', 'message': f'Starting discovery for {subject_name}...', 'subject_id': active_subject_id})}\n\n"
                
                for update in core.discover_comps_live(subject, active_subject_id, force_verify=init_force):
                    yield f"data: {json.dumps(update)}\n\n"
                    if update['status'] == 'complete':
                        break 
                    await asyncio.sleep(0.001)
                
                yield f"data: {json.dumps({'status': 'info', 'message': 'Discovery complete. Preparing curation dashboard...'})}\n\n"

            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sales_comps WHERE target_property_id = ? AND status != 'REJECTED'", (active_subject_id,))
            comps = [dict(row) for row in cursor.fetchall()]
            conn.close()

            if not comps:
                yield f"data: {json.dumps({'status': 'no_comps', 'message': 'No matching sales found.', 'subject_id': active_subject_id})}\n\n"
                return

            condition_factors = {"below": 0.85, "average": 1.00, "above": 1.10, "renovated": 1.20}
            condition_factor = condition_factors.get((init_condition or "average").lower(), 1.0)

            valuation = core.calculate_valuation(
                subject, comps,
                renovation_year=init_renov,
                condition_factor=condition_factor,
                enforce_selection=False
            )

            sorted_comps = sorted([c for c in valuation["comps"] if c.get('status') != 'REJECTED'], key=lambda x: x.get('similarity_score', 0), reverse=True)

            html_content = templates.get_template("curation.html").render({
                "request": request,
                "subject": subject,
                "subject_id": active_subject_id,
                "comps": sorted_comps,
                "renovation_year": init_renov,
                "condition": init_condition,
            })
            
            payload = json.dumps({"status": "render_ui", "html": html_content})
            yield f"data: {payload}\n\n"

        except Exception as e:
            traceback.print_exc()
            await send_error_report(str(e), traceback.format_exc())
            yield f"data: {json.dumps({'status': 'error', 'message': f'System error: {str(e)}'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/add_comp")
async def add_comp(request: Request, property_id: int = Form(...), address: str = Form(...), price: float = Form(...)):
    success, msg = core.add_manual_comp(property_id, address, price)
    
    if "application/json" in request.headers.get("accept", ""):
        from fastapi.responses import JSONResponse
        if success:
            return JSONResponse({"status": "success", "message": msg})
        else:
            return JSONResponse({"status": "error", "message": msg}, status_code=400)
            
    if success:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT address FROM properties WHERE id = ?", (property_id,))
        row = cursor.fetchone()
        conn.close()
        subject_addr = row[0] if row else ""
        return HTMLResponse(f"""
            <div style="font-family:sans-serif; text-align:center; padding:50px;">
                <h2>Comp Added!</h2>
                <p>We've verified and added <b>{address}</b> to your property record.</p>
                <br>
                <form action="/report" method="post">
                    <input type="hidden" name="address" value="{subject_addr}">
                    <input type="hidden" name="subject_id" value="{property_id}">
                    <input type="hidden" name="update_curation" value="true">
                    <button type="submit" style="padding:10px 20px; background:#27ae60; color:white; border:none; border-radius:4px; cursor:pointer;">Show Report</button>
                </form>
            </div>
        """)
    else:
        return HTMLResponse(f"Failed to add comp: {msg}")

def _build_report_context(subject_id: int, renovation_year: int = None, condition: str = "average"):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM properties WHERE id = ?", (subject_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None
    subject = dict(row)
    # FOR PDF: We only use SELECTED comps
    cursor.execute(
        "SELECT * FROM sales_comps WHERE target_property_id = ? AND status != 'REJECTED' AND is_selected = 1",
        (subject_id,),
    )
    comps = [dict(r) for r in cursor.fetchall()]
    conn.close()

    condition_factors = {"below": 0.85, "average": 1.00, "above": 1.10, "renovated": 1.20}
    valuation = core.calculate_valuation(
        subject, comps,
        renovation_year=renovation_year,
        condition_factor=condition_factors.get((condition or "average").lower(), 1.0),
        enforce_selection=True
    )

    from app.equalization import get_rate as _er_rate, implied_market_value
    er = _er_rate(subject.get('sbl'))
    current_av = subject.get('assessment_2026') or subject.get('assessment_2025') or 0
    implied_mv = implied_market_value(current_av, subject.get('sbl')) if current_av else None
    if implied_mv:
        reduction_full = max(0.0, float(implied_mv) - float(valuation["market_value"]))
        reduction_av = reduction_full * (er / 100.0) if er else reduction_full
    else:
        reduction_full = max(0.0, float(current_av) - float(valuation["market_value"]))
        reduction_av = reduction_full

    from app.bar_info import get_bar
    return {
        "subject": subject,
        "subject_id": subject_id,
        "comps": valuation["comps"],
        "market_value": valuation["market_value"],
        "range_low": valuation["range_low"],
        "range_high": valuation["range_high"],
        "used_count": valuation["used_count"],
        "considered_count": valuation["considered_count"],
        "adjustments_used": valuation["adjustments_used"],
        "current_av": current_av,
        "equalization_rate": er,
        "implied_market_value": implied_mv,
        "reduction": reduction_av,
        "reduction_full": reduction_full,
        "renovation_year": renovation_year,
        "condition": condition,
        "bar_info": get_bar(subject.get('sbl')),
    }


@app.get("/grievance/rp524.pdf")
async def grievance_rp524(subject_id: int, renovation_year: int = None, condition: str = "average",
                          owner_name: str = None, owner_address: str = None, owner_email: str = None, owner_phone: str = None):
    from fastapi.responses import Response
    from app.pdf_gen import render_rp524
    ctx = _build_report_context(subject_id, renovation_year, condition)
    if not ctx:
        return JSONResponse({"error": "Property not found"}, status_code=404)
    ctx.update({
        "owner_name": owner_name,
        "owner_address": owner_address,
        "owner_email": owner_email,
        "owner_phone": owner_phone
    })
    pdf_bytes = render_rp524(ctx)
    safe = (ctx["subject"].get("address") or "subject").replace("/", "-").replace(" ", "_")
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="RP-524_{safe}.pdf"'})


@app.get("/grievance/methodology.pdf")
async def grievance_methodology(subject_id: int, renovation_year: int = None, condition: str = "average"):
    from fastapi.responses import Response
    from app.pdf_gen import render_methodology
    ctx = _build_report_context(subject_id, renovation_year, condition)
    if not ctx:
        return JSONResponse({"error": "Property not found"}, status_code=404)
    pdf_bytes = render_methodology(ctx)
    safe = (ctx["subject"].get("address") or "subject").replace("/", "-").replace(" ", "_")
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="Methodology_{safe}.pdf"'})


@app.get("/grievance/package.zip")
async def grievance_package(subject_id: int, renovation_year: int = None, condition: str = "average",
                            owner_name: str = None, owner_address: str = None, owner_email: str = None, owner_phone: str = None):
    from fastapi.responses import Response
    from app.pdf_gen import render_rp524, render_methodology
    import zipfile, io
    ctx = _build_report_context(subject_id, renovation_year, condition)
    if not ctx:
        return JSONResponse({"error": "Property not found"}, status_code=404)
    ctx.update({
        "owner_name": owner_name,
        "owner_address": owner_address,
        "owner_email": owner_email,
        "owner_phone": owner_phone
    })
    rp524 = render_rp524(ctx)
    method = render_methodology(ctx)

    safe = (ctx["subject"].get("address") or "subject").replace("/", "-").replace(" ", "_")

    bar = ctx.get("bar_info") or {}
    cover = (
        f"To: {bar.get('municipality') or 'The Board of Assessment Review'}\n"
        f"    {bar.get('bar_address') or ''}\n\n"
        f"Re: Complaint on real property assessment — {ctx['subject'].get('address')}\n"
        f"    SBL: {ctx['subject'].get('sbl')}\n\n"
        f"Enclosed please find a completed Form RP-524 challenging the {ctx['subject'].get('town') or 'municipal'} assessment\n"
        f"of {ctx['subject'].get('address')} for the 2025 tax roll. The current assessed value of "
        f"${(ctx.get('current_av') or 0):,.0f} at the {ctx.get('equalization_rate', 100):.2f}% "
        f"equalization rate implies a full market value of "
        f"${(ctx.get('implied_market_value') or 0):,.0f}.\n\n"
        f"A sales-comparison analysis using {ctx.get('used_count')} recent comparable sales in the\n"
        f"immediate market area indicates a full market value of approximately "
        f"${(ctx.get('market_value') or 0):,.0f}, with an inter-quartile range of "
        f"${(ctx.get('range_low') or 0):,.0f}–${(ctx.get('range_high') or 0):,.0f}.\n\n"
        f"I respectfully request that the assessment be reduced by ${(ctx.get('reduction') or 0):,.0f}, "
        f"from ${(ctx.get('current_av') or 0):,.0f} to ${((ctx.get('current_av') or 0) - (ctx.get('reduction') or 0)):,.0f}, "
        f"to reflect actual market conditions.\n\n"
        f"The methodology appendix details the adjustment factors, outlier filter, and limitations "
        f"of this estimate. I am available at the BAR hearing to discuss.\n\n"
        f"Sincerely,\n\n"
        f"___________________________\n"
        f"Property Owner"
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"01_Cover_Letter_{safe}.txt", cover)
        zf.writestr(f"02_RP-524_{safe}.pdf", rp524)
        zf.writestr(f"03_Methodology_{safe}.pdf", method)
        zf.writestr("README.txt",
                    "Property tax grievance evidence package\n"
                    "=======================================\n\n"
                    "01_Cover_Letter — print, sign, mail with the form.\n"
                    "02_RP-524       — filled-out NYS Form RP-524. Verify all fields and sign Part 5.\n"
                    "03_Methodology  — explains the math; attach as an exhibit to the form.\n\n"
                    "Before filing: confirm Grievance Day and submission method with your local "
                    "assessor's office. Filing instructions are at the bottom of the RP-524 PDF.\n")
    buf.seek(0)
    return Response(content=buf.read(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="Grievance_Package_{safe}.zip"'})


@app.get("/bar_info")
async def bar_info(subject_id: int):
    from app.bar_info import get_bar
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT sbl FROM properties WHERE id = ?", (subject_id,))
    row = cursor.fetchone()
    conn.close()
    if not row or not row['sbl']:
        return JSONResponse({})
    info = get_bar(row['sbl'])
    if not info:
        return JSONResponse({
            "municipality": "Unknown municipality",
            "notes": "Filing information for this municipality is not yet in our database. Look up your local assessor's office and confirm Grievance Day (typically the 4th Tuesday in May for towns).",
        })
    return JSONResponse(info)


@app.post("/select_comp")
async def select_comp(property_id: int = Form(...), zpid: str = Form(None), address: str = Form(None)):
    conn = get_connection()
    cursor = conn.cursor()
    if zpid:
        cursor.execute("UPDATE sales_comps SET is_selected = 1 WHERE target_property_id = ? AND zpid = ?", (property_id, zpid))
    else:
        cursor.execute("UPDATE sales_comps SET is_selected = 1 WHERE target_property_id = ? AND address = ?", (property_id, address))
    conn.commit()
    conn.close()
    return {"status": "success"}


@app.post("/unselect_comp")
async def unselect_comp(property_id: int = Form(...), zpid: str = Form(None), address: str = Form(None)):
    conn = get_connection()
    cursor = conn.cursor()
    if zpid:
        cursor.execute("UPDATE sales_comps SET is_selected = 0 WHERE target_property_id = ? AND zpid = ?", (property_id, zpid))
    else:
        cursor.execute("UPDATE sales_comps SET is_selected = 0 WHERE target_property_id = ? AND address = ?", (property_id, address))
    conn.commit()
    conn.close()
    return {"status": "success"}


@app.post("/reject_comp")
async def reject_comp(request: Request, property_id: int = Form(...), address: str = Form(...), zpid: str = Form(None), reason: str = Form(None)):
    conn = get_connection()
    cursor = conn.cursor()
    if zpid:
        cursor.execute("UPDATE sales_comps SET status = 'REJECTED', rejection_reason = ? WHERE target_property_id = ? AND zpid = ?", (reason, property_id, zpid))
    else:
        cursor.execute("UPDATE sales_comps SET status = 'REJECTED', rejection_reason = ? WHERE target_property_id = ? AND address = ?", (reason, property_id, address))
    conn.commit()
    conn.close()
    return {"status": "success"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
