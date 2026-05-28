from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.core import TaxGrieveCore
from app.utils import send_error_report, init_sentry
from app.counties.factory import CountyFactory
from app.counties.dutchess import DutchessCounty
from app.counties.ulster import UlsterCounty
from app.db import get_connection, init_schema
from app.tos_gate import COOKIE_NAME as TOS_COOKIE, TTL_SECONDS as TOS_TTL, make_cookie as make_tos_cookie, require_tos_accepted
import traceback
import json
import re
import requests
from fastapi.responses import StreamingResponse
import asyncio
import os
from dotenv import load_dotenv
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

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
init_sentry()


def _client_ip(request: Request) -> str:
    """Per-IP key for rate limiting. Cloud Run sets X-Forwarded-For with the
    real client IP first in the chain, so prefer that over the proxy address."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(key_func=_client_ip, default_limits=["120/hour"])

app = FastAPI()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
# Apply canonical schema once at startup. Idempotent — CREATE TABLE IF NOT
# EXISTS + CREATE INDEX IF NOT EXISTS in both schema files.
init_schema()
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


def _format_autocomplete_value(address: str, town: str, zip5: str = "") -> str:
    parts = [p for p in [address, town, "NY"] if p]
    value = ", ".join(parts)
    return f"{value} {zip5}".strip() if zip5 else value


def _normalize_parcel_suggestion(item: dict) -> dict:
    address = (item.get("address") or "").strip()
    town = (item.get("town") or "").strip()
    zip5 = (item.get("zip") or "").strip()[:5]
    if not zip5 and address and town:
        _, _, zip5 = core._geocode(f"{address}, {town}, NY")
        zip5 = (zip5 or "").strip()[:5]
    county = item.get("county") or _county_for_zip(zip5) or ""
    label = _format_autocomplete_value(address, town, zip5)
    return {
        "label": label,
        "value": label,
        "address": address,
        "town": town,
        "county": county,
        "zip": zip5,
        "parcelgrid": item.get("parcelgrid") or item.get("sbl") or "",
        "sbl": item.get("sbl") or item.get("parcelgrid") or "",
        "swis": item.get("swis") or "",
        "source": "parcel",
    }


def _parcel_autocomplete(q: str, limit: int = 8, swis_options: list[str] = None) -> list[dict]:
    detected = CountyFactory.detect_county(address_string=q)
    handlers = [UlsterCounty(timeout=4)] if detected == "ulster" else [DutchessCounty()]

    suggestions = []
    seen = set()
    for handler in handlers:
        if not hasattr(handler, "suggest_addresses"):
            continue
        try:
            kwargs = {}
            if isinstance(handler, DutchessCounty) and swis_options is not None:
                kwargs["swis_options"] = swis_options
            for item in handler.suggest_addresses(q, limit=limit, **kwargs):
                normalized = _normalize_parcel_suggestion(item)
                key = normalized.get("parcelgrid") or (normalized["address"].upper(), normalized.get("zip"))
                if key in seen:
                    continue
                seen.add(key)
                suggestions.append(normalized)
                if len(suggestions) >= limit:
                    return suggestions
        except Exception as e:
            print(f"parcel autocomplete error: {e}")
    return suggestions


def _census_autocomplete(q: str, limit: int = 8, existing_keys=None, timeout: float = 6) -> tuple[list[dict], str]:
    existing_keys = existing_keys or set()
    address_query = q if re.search(r"\bNY\b", q, re.IGNORECASE) else f"{q}, NY"
    try:
        resp = requests.get(
            CENSUS_GEOCODER_URL,
            params={"address": address_query, "benchmark": "Public_AR_Current", "format": "json"},
            timeout=timeout,
        )
        resp.raise_for_status()
        matches = resp.json().get("result", {}).get("addressMatches", []) or []
    except Exception as e:
        print(f"autocomplete error: {e}")
        return [], str(e)

    suggestions = []
    seen = set(existing_keys)
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
        value = _format_autocomplete_value(street, city, zipc)
        suggestions.append({
            "label": value,
            "value": value,
            "address": street,
            "town": city,
            "county": county,
            "zip": zipc,
            "parcelgrid": "",
            "sbl": "",
            "source": "census",
        })
        if len(suggestions) >= limit:
            break
    return suggestions, ""


@app.get("/autocomplete")
@limiter.limit("180/minute")
async def autocomplete(request: Request, q: str = ""):
    """Address suggestions for Dutchess + Ulster.

    Parcel-backed suggestions come first so the selected result can carry an
    authoritative SBL into /search_property. Census Geocoder results remain as
    a fallback for broad/no-town queries and ZIP normalization.
    """
    q = (q or "").strip()
    m = re.match(r"^\s*(\d+)\s+(\S.{2,})$", q)
    if not m:
        return JSONResponse({"suggestions": []})

    cache_key = q.upper()
    if cache_key in _AC_CACHE:
        return JSONResponse({"suggestions": _AC_CACHE[cache_key]})

    # Detect county to decide optimization path
    detected_county = CountyFactory.detect_county(address_string=q)
    
    swis_options = None
    if detected_county == "dutchess":
        dutchess_handler = DutchessCounty()
        # If user explicitly types a town name, use that swis only (fast)
        explicit_swis = [
            code for code, name in dutchess_handler.swis_map.items()
            if name.upper() in q.upper()
        ]
        if explicit_swis:
            swis_options = explicit_swis
        else:
            # Query Census geocoder first with a short timeout to extract town name
            # and avoid querying 29 municipalities in parallel on the Dutchess server.
            try:
                census_candidates, _ = _census_autocomplete(q, limit=5, timeout=2.0)
                candidate_swis = set()
                for item in census_candidates:
                    if item.get("county") == "Dutchess":
                        for code, name in dutchess_handler.swis_map.items():
                            if name.lower() == item["town"].lower():
                                candidate_swis.add(code)
                if candidate_swis:
                    swis_options = list(candidate_swis)
            except Exception as ce:
                print(f"Census pre-flight for swis search failed: {ce}")

    suggestions = _parcel_autocomplete(q, limit=8, swis_options=swis_options)
    existing_keys = {(s["address"].upper(), s.get("zip")) for s in suggestions}
    if len(suggestions) < 8:
        census_items, census_error = _census_autocomplete(q, limit=8 - len(suggestions), existing_keys=existing_keys)
        suggestions.extend(census_items)
    else:
        census_error = ""

    if len(_AC_CACHE) >= _AC_CACHE_MAX:
        _AC_CACHE.pop(next(iter(_AC_CACHE)))
    _AC_CACHE[cache_key] = suggestions
    body = {"suggestions": suggestions}
    if not suggestions and census_error:
        body["error"] = census_error
    return JSONResponse(body)

@app.post("/search_property")
@limiter.limit("30/hour")
async def search_property(
    request: Request,
    address: str = Form(...),
    parcelgrid: str = Form(None),
    sbl: str = Form(None),
    county: str = Form(None),
    zip_code: str = Form(None),
):
    try:
        address = address.strip()
        identifier = (parcelgrid or sbl or "").strip()
        zip_code = (zip_code or "").strip()[:5] or None
        if identifier:
            subject = core.get_subject_profile_by_identifier(identifier, address_string=address, zip_code=zip_code)
        else:
            subject = core.get_subject_profile(address)
        if not subject:
            return {"status": "error", "message": f"Property not found: {address}"}
        
        subject_id = core.ensure_property(subject)
        # SBL-based routing is authoritative — it embeds the SWIS code which
        # tells us the actual county regardless of what was typed.
        county_handler = CountyFactory.get_county_handler(address_string=address, zip_code=zip_code, sbl=subject.get('sbl'))
        subject['town'] = county_handler.get_town_from_identifier(subject['sbl'])
        
        return {
            "status": "success",
            "subject": subject,
            "subject_id": subject_id
        }
    except Exception as e:
        send_error_report(e, {"address": address, "phase": "search_property"})
        return {"status": "error", "message": str(e)}

@app.post("/report")
@limiter.limit("20/hour")
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
            
            cursor = conn.cursor()
            if init_finalize:
                cursor.execute("SELECT * FROM sales_comps WHERE target_property_id = ? AND is_selected = 1", (active_subject_id,))
            else:
                cursor.execute("SELECT * FROM sales_comps WHERE target_property_id = ?", (active_subject_id,))
            all_comps = [dict(row) for row in cursor.fetchall()]
            conn.close()

            if not all_comps:
                return HTMLResponse("No comps found or selected.", status_code=400)

            condition_factors = {"below": 0.85, "average": 1.00, "above": 1.10, "renovated": 1.20}
            condition_factor = condition_factors.get((init_condition or "average").lower(), 1.0)

            valuation = core.calculate_valuation(
                subject, all_comps,
                renovation_year=init_renov,
                condition_factor=condition_factor,
                enforce_selection=init_finalize
            )

            if init_finalize and valuation["used_count"] < 3:
                return HTMLResponse(
                    "Select at least 3 defensible comparable sales before finalizing.",
                    status_code=400,
                )
            
            if init_update_curation:
                sorted_comps = sorted(valuation["comps"], key=lambda x: x.get('similarity_score', 0), reverse=True)
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
            cursor.execute("SELECT * FROM sales_comps WHERE target_property_id = ?", (active_subject_id,))
            all_comps = [dict(row) for row in cursor.fetchall()]
            conn.close()

            if not all_comps:
                yield f"data: {json.dumps({'status': 'no_comps', 'message': 'No comparable sales found. Add manual comps or broaden the search.', 'subject_id': active_subject_id})}\n\n"
                return

            condition_factors = {"below": 0.85, "average": 1.00, "above": 1.10, "renovated": 1.20}
            condition_factor = condition_factors.get((init_condition or "average").lower(), 1.0)

            valuation = core.calculate_valuation(
                subject, all_comps,
                renovation_year=init_renov,
                condition_factor=condition_factor,
                enforce_selection=False
            )

            sorted_comps = sorted(valuation["comps"], key=lambda x: x.get('similarity_score', 0), reverse=True)

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
            send_error_report(e, {"phase": "report_stream", "traceback": traceback.format_exc()})
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
        subject_addr = row['address'] if row else ""
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
        "SELECT * FROM sales_comps WHERE target_property_id = ? AND is_selected = 1",
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


_TOS_PAGE_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Acknowledgement — griever</title>
<style>
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; max-width: 720px; margin: 40px auto; padding: 20px; color: #2c3e50; line-height: 1.55; }
h1 { color: #1a252f; }
.box { background: #fffaf0; border: 1px solid #f0d9a8; padding: 18px; border-radius: 4px; margin: 20px 0; }
.box ul { margin: 10px 0 0 0; padding-left: 20px; }
button { background: #27ae60; color: white; border: none; padding: 12px 24px; font-size: 15px; border-radius: 4px; cursor: pointer; }
button:hover { background: #1e8449; }
.cancel { background: #95a5a6; margin-left: 8px; }
.cancel:hover { background: #7f8c8d; }
</style></head>
<body>
<h1>Before downloading your grievance package</h1>
<p>The PDF you are about to download is generated by an automated valuation model. Please acknowledge the following before proceeding.</p>
<div class="box">
<ul>
<li>This report is <strong>not</strong> a certified appraisal and does not constitute legal or tax advice.</li>
<li>Filing decisions and the accuracy of any RP-524 you submit are <strong>your sole responsibility</strong>.</li>
<li>For high-value or complex properties, consult a licensed real-estate appraiser or tax-grievance attorney.</li>
<li>griever is not liable for errors in third-party data sources (NYS ORPTS, Dutchess/Ulster county records, Zillow/RapidAPI listings).</li>
</ul>
</div>
<form method="post" action="/accept_tos">
  <input type="hidden" name="next" value="{next_url}">
  <button type="submit">I acknowledge — continue to download</button>
  <a href="{back_url}"><button type="button" class="cancel">Cancel</button></a>
</form>
</body></html>
"""


@app.post("/accept_tos")
async def accept_tos(request: Request, next: str = Form("/")):
    """Set the ToS-accepted cookie and bounce the user back to where they
    came from (typically the report page that linked to the PDF)."""
    from fastapi.responses import RedirectResponse
    # Allow only same-origin relative paths to defeat open-redirect abuse.
    safe_next = next if next.startswith("/") and not next.startswith("//") else "/"
    resp = RedirectResponse(url=safe_next, status_code=303)
    resp.set_cookie(
        TOS_COOKIE,
        make_tos_cookie(),
        max_age=TOS_TTL,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )
    return resp


def _tos_gate_redirect(request: Request) -> HTMLResponse:
    """Render the gate page with the current URL stashed so /accept_tos can
    bounce back to it after acceptance."""
    next_url = str(request.url.path)
    if request.url.query:
        next_url = f"{next_url}?{request.url.query}"
    # Use .replace() rather than .format() — the embedded CSS has literal
    # '{' / '}' that confuse Python's format-string parser.
    import html as _html
    rendered = (
        _TOS_PAGE_HTML
        .replace("{next_url}", _html.escape(next_url, quote=True))
        .replace("{back_url}", "/")
    )
    return HTMLResponse(rendered)


@app.get("/grievance/rp524.pdf")
@limiter.limit("10/day")
async def grievance_rp524(request: Request, subject_id: int, renovation_year: int = None, condition: str = "average",
                          owner_name: str = None, owner_address: str = None, owner_email: str = None, owner_phone: str = None):
    if not require_tos_accepted(request):
        return _tos_gate_redirect(request)
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
@limiter.limit("20/day")
async def grievance_methodology(request: Request, subject_id: int, renovation_year: int = None, condition: str = "average"):
    if not require_tos_accepted(request):
        return _tos_gate_redirect(request)
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
@limiter.limit("10/day")
async def grievance_package(request: Request, subject_id: int, renovation_year: int = None, condition: str = "average",
                            owner_name: str = None, owner_address: str = None, owner_email: str = None, owner_phone: str = None):
    if not require_tos_accepted(request):
        return _tos_gate_redirect(request)
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


@app.post("/restore_comp")
async def restore_comp(property_id: int = Form(...), zpid: str = Form(None), address: str = Form(None)):
    conn = get_connection()
    cursor = conn.cursor()
    if zpid:
        cursor.execute("""
            UPDATE sales_comps 
            SET status = CASE WHEN sbl = 'UNVERIFIED' THEN 'UNVERIFIED' ELSE 'VERIFIED' END 
            WHERE target_property_id = ? AND zpid = ?
        """, (property_id, zpid))
    else:
        cursor.execute("""
            UPDATE sales_comps 
            SET status = 'MANUAL' 
            WHERE target_property_id = ? AND address = ?
        """, (property_id, address))
    conn.commit()
    conn.close()
    return {"status": "success"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
