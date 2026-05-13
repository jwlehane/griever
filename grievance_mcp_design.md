# Property Tax Grievance Pipeline Design

## Objective
Automate local market data retrieval and valuation adjustments for residential property tax grievances in New York State (currently supporting Dutchess and Ulster counties). The system provides a deterministic, data-driven analysis to support RP-524 filings.

## Architecture
The application is a Python-based FastAPI web server that orchestrates the following flow:

### 1. Subject Identification & Profiling
- **Entry:** User provides a street address.
- **Geocoding:** US Census Geocoder provides Lat/Lon and ZIP for distance math and county routing.
- **County API:**
    - **Dutchess:** Direct calls to `gis.dutchessny.gov/parcelaccess`.
    - **Ulster:** Direct calls to `gisservices.its.ny.gov` (ArcGIS REST API).
- **Official Records:** Authoritative parcel data (SBL, Assessment, Sqft, Year Built) is retrieved directly from municipal RPS systems.
- **Enrichment:** RapidAPI (Real-Time Real-Estate Data) is queried to backfill any missing characteristic data.

### 2. Market Discovery
- **RapidAPI:** Queries for recent "SOLD" listings within a 1-mile radius (default) matching subject's bedrooms/bathrooms.
- **Live Streaming:** Results are streamed to the UI via Server-Sent Events (SSE) as they are verified.

### 3. Verification & Normalization
- **Self-Verification:** Each discovered comp is verified against the subject's county API (if possible) or geocoded to ensure it is within the same municipality.
- **Storage:** Data is normalized and cached in a local SQLite database (`grievance_data.db`).

### 4. Valuation Logic
- **Similarity Scoring:** Comps are scored (0-100) based on Sqft (40%), Effective Age (30%), Acreage (20%), and Distance (10%).
- **Adjustments:** Per-municipality factors (e.g., $150/sqft, $15k/bath) are applied to calculate a "Reconciled Value" for each comp.
- **Outlier Detection:** Tukey's Fence (1.5x IQR) is applied to filtered out extreme sales.
- **Final Estimate:** The median of the top-5 non-outlier comps is used as the defensible market value.

### 5. Reporting & Evidence
- **Web UI:** Interactive report showing all considered comps, applied adjustments, and a suggested grievance narrative.
- **PDF Generation:** Automated generation of a filled NYS Form RP-524 and a comprehensive "Evidence Package" using ReportLab.

## Tech Stack
- **Backend:** FastAPI (Python 3.11)
- **Database:** SQLite
- **PDF Gen:** ReportLab
- **Frontend:** Jinja2 + Vanilla CSS + SSE
- **Integration:** US Census Geocoder, RapidAPI, County ParcelAccess APIs.
