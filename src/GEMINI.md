# TaxGrieve Web Service

## Running Locally
1. Activate the virtual environment: `source tax-grieve-env/bin/activate`
2. Install requirements: `pip install -r requirements.txt`
3. Run the app: `python3 src/main.py`
4. Visit `http://localhost:8080`

## Deployment
This application is designed for **Google Cloud Run**. 
- Scaling: 0 to N (Very cost-effective)
- Port: 8080
- Memory: 512MB is sufficient.

## Architecture
- **Backend:** FastAPI (Python)
- **Logic:** `src/app/core.py` (Deterministic logic, zero token cost)
- **Data:** SQLite (`grievance_data.db`)
- **Frontend:** Jinja2 templates with minimalist CSS.
