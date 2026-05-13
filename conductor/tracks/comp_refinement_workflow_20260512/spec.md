# Specification: Comp Refinement Workflow & Documentation Sync

## Goal
Improve the "Human-in-the-Loop" aspect of the grievance pipeline by providing better control over comparable sales selection and ensuring the project's technical documentation accurately reflects the current state of the application.

## User Experience (UX)
1.  **Pre-Discovery:** User should see a summary of their own property details *before* the market search starts, confirming the data that will be used for filtering.
2.  **Interactive Selection:** After discovery, the report page should clearly distinguish between "Used" comps and "Available" comps.
3.  **Substitution:** User should be able to click a "Substitute" or "Use this instead" button on an available comp to swap it into the primary valuation set.
4.  **Ranking:** Comps should be ranked by similarity, but users should have the ability to manually influence this ranking (e.g., "Pin to top").
5.  **Enhanced Rejection:** When rejecting a comp, the user should be able to provide a reason (e.g., "Too close to highway", "Poor condition").

## Functional Requirements
- **Documentation Sync:** Update `grievance_mcp_design.md` and `conductor/product.md` to reflect the FastAPI architecture, Ulster support, and PDF generation capabilities.
- **Pre-Search Check:** Implement a check in `src/main.py` that confirms subject data sufficiency (sqft, bedrooms, bathrooms) before triggering the RapidAPI discovery.
- **Comp Ranking Logic:** Refactor `calculate_valuation` to support "pinned" or "manually selected" comps that override the default similarity-based selection.
- **Substitution API:** New endpoint `@app.post("/select_comp")` to manually mark a comp for inclusion in the report.
- **Rejection Reasons:** Update `sales_comps` schema to store rejection reasons.

## Technical Standards
- Maintain 100% test coverage for new valuation logic.
- Ensure all API endpoints are idempotent where possible.
- Update the PDF generation to include user-provided rejection reasons or notes if appropriate.
