# Implementation Plan: Implement Property Data Discovery and SQLite Normalization

## Phase 1: Discovery (RapidAPI)
- [ ] Task: Configure `RAPIDAPI_KEY` environment variable.
- [ ] Task: Execute `tools/fetch_comps.sh` and validate JSON structure.
- [ ] Task: Extract addresses from discovery results for verification.

## Phase 2: Verification (Playwright & ParcelAccess)
- [ ] Task: Navigate to ParcelAccess and identify selectors for property search and data fields.
- [ ] Task: Extract SBL and 2026 Assessment for the subject property (67 N Parsonage St).
- [ ] Task: Extract physical characteristics (sqft, acreage) for subject and comps.

## Phase 3: Storage & Normalization (SQLite)
- [ ] Task: Insert subject property data into the `properties` table.
- [ ] Task: Normalize comp data and insert into the `sales_comps` table.
- [ ] Task: Verify data integrity with a cross-table SQL query.
