# Tech Stack: Property Tax Grievance Pipeline

## Architecture
- **Backend Framework:** FastAPI (Python 3.11)
- **Data Logic:** Deterministic logic encapsulated in `src/app/core.py` with county-specific handlers in `src/app/counties/`.
- **Frontend:** Jinja2 templates (`src/templates/`) with Vanilla CSS and Server-Sent Events (SSE) for live tracking.

## Storage
- **Database:** SQLite (`grievance_data.db`) for normalized data storage and valuation records.

## PDF Generation
- **Library:** ReportLab Platypus for high-fidelity generation of filled RP-524 forms and evidence appendices.

## Languages & Tools
- **Python 3.11:** Primary language for all application logic.
- **Pytest:** Automated unit and integration testing framework.
- **HTTP Clients:** `requests` for geocoding and county APIs.
- **Retrying:** `tenacity` for robust API communication.

## External APIs
- **RapidAPI (Real-Time Real-Estate Data):** Primary source for recent residential sales comps.
- **Dutchess County ParcelAccess:** Direct ASP API for official records.
- **Ulster County / NYS Tax Parcels:** ArcGIS REST API for official records.
- **US Census Geocoder:** authoritative address normalization and Lat/Lon lookup.

## Deployment Target
- **Google Cloud Run:** Primary hosting platform.
- **Cloud Load Balancing:** Handles custom domain SSL for `griever.johnnylehane.com`.
