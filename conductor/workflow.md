# Workflow: Property Tax Grievance Pipeline

## Phase 1: Discovery
- Execute `curl` to RapidAPI for 3-4 bedroom sales in Rhinebeck.
- Pipe JSON results into the CLI context.

## Phase 2: Verification
- Use Playwright MCP to visit ParcelAccess for specific addresses.
- Extract: SBL, 2026 assessed value, square footage, bedrooms/bathrooms, acreage.

## Phase 3: Storage & Normalization
- Parse data into a structured format.
- Use SQLite MCP to insert records into `grievance_data.db`.

## Phase 4: Valuation Adjustments
- Apply adjustments for differences between subject property and comps:
    - Square footage delta.
    - Bedroom/Bathroom delta.
    - Acreage delta.
- Calculate "Reconciled Value" per comp.

## Phase 5: Document Generation
- Select top 3 comps.
- Generate Markdown narrative for RP-524.
