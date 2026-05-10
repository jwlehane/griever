# Implementation Plan: Implement Property Data Discovery and SQLite Normalization

## Phase 1: Discovery (RapidAPI)
- [x] Task: Configure `RAPIDAPI_KEY` environment variable.
- [x] Task: Execute `tools/fetch_comps.sh` and validate JSON structure.
- [x] Task: Extract addresses from discovery results for verification.

## Phase 2: Verification (Direct API & ParcelAccess)
- [x] Task: Reverse engineer ParcelAccess ASP endpoints to bypass WebGL limitations.
- [x] Task: Extract SBL (ParcelGrid) and Assessment for subject properties via API.
- [x] Task: Extract physical characteristics for subject properties via API.
- [x] Task: Extract physical characteristics for curated comps via API.
- [x] Task: Resolve 1557 Centre Rd (Clinton) data discrepancy.

## Phase 3: Automated Broad Discovery
- [ ] Task: Create `tools/discover_sales.py` to automatically query county sales API based on subject property profile.
- [ ] Task: Implement "Similarity Scoring" logic to automatically rank the top 10 best comps from the broad search.
- [ ] Task: Store discovery results in `sales_comps` table tagged with `source='API_DISCOVERY'`.

## Phase 4: Valuation & Suggestion Engine
- [x] Task: Implement first-pass valuation math script (`tools/calculate_valuation.py`).
- [ ] Task: Implement Outlier Detection (e.g., filter sales > 150% of subject's sqft).
- [ ] Task: Create "Suggestive Feedback" logic (e.g., "Recommended: Remove 38 Chestnut to strengthen case").

## Phase 5: Web Service Scaffolding
- [x] Task: Create a FastAPI wrapper to expose the pipeline as an API (`src/main.py`).
- [x] Task: Build a simple React or Vanilla JS frontend to accept an address and display the report (`src/templates/`).
- [x] Task: Create `Dockerfile` for Cloud Run deployment.
- [ ] Task: Deploy to Google Cloud Run (Pending user preference).

## Phase: Review Fixes
- [x] Task: Apply review suggestions ede1e28
- [x] Task: Apply review suggestions cb84793


