# Workflow: Property Tax Grievance Pipeline

## Phase 1: Input & Subject Profile
- User enters an address via the web interface.
- System queries RapidAPI and County APIs to build a subject property profile.

## Phase 2: Discovery
- Execute queries to RapidAPI for recent sales comps matching the subject's criteria.
- Stream live results back to the frontend via Server-Sent Events (SSE).

## Phase 3: Verification
- Use Direct API calls to query County ParcelAccess (abstracted via county interfaces) for specific addresses.
- Extract: SBL, assessed value, square footage, bedrooms/bathrooms, acreage, year built.

## Phase 4: Storage & Normalization
- Parse data into a structured format.
- Insert records into `grievance_data.db` (SQLite).

## Phase 5: Refinement & Valuation Adjustments
- If needed, prompt user for renovation year to calculate "Effective Year Built".
- Apply adjustments for differences between subject property and comps (Sqft, Beds/Baths, Acreage, Effective Age).
- Apply similarity scoring and detect outliers.
- Calculate "Reconciled Value" per comp.

## Phase 6: Document Generation & Review
- Display top comps in the web UI.
- Allow human-in-the-loop rejection/addition of comps.
- Generate Markdown narrative for RP-524.
