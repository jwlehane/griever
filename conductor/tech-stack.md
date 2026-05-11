# Tech Stack: Property Tax Grievance Pipeline

## Architecture
- **Backend Framework:** FastAPI (Python 3.11)
- **Data Logic:** Deterministic logic encapsulated in `src/app/core.py` and county-specific modules.
- **Frontend:** Jinja2 templates (`src/templates/`) with minimalist CSS and Server-Sent Events (SSE) for live tracking.

## Storage
- **Database:** SQLite (`grievance_data.db`) for normalized data storage and valuation records.

## Languages & Tools
- **Python 3.11:** Primary language for all application logic.
- **Pytest:** Automated unit and integration testing framework.
- **HTTP Clients:** `httpx` or `requests` for RapidAPI and County API integrations.

## External APIs
- **RapidAPI (Real-Time Real-Estate Data):** Source for recent sales comps.
- **County APIs:** Direct ASP/API endpoints for official property records (Dutchess, Ulster).

## Deployment Target
- **Google Cloud Run:** Targeted hosting platform. Scales to zero, listens on port 8080.
