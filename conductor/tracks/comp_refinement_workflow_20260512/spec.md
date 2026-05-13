# Specification: Comp Refinement & NYS Best Practices Workflow

## Goal
Improve the "Human-in-the-Loop" pipeline by enforcing New York State appraisal best practices. Provide an interactive workflow where users review, grade, and select comparable sales *before* the final valuation is calculated, ensuring a defensible and high-quality grievance submission.

## NYS Industry Best Practices to Enforce & Explain
1.  **The Valuation Date Rule:** NYS typically uses July 1 of the preceding year (e.g., July 1, 2024, for the 2025 roll). Sales must be evaluated based on their proximity to this date.
2.  **Arms-Length Transactions:** The system must explain that foreclosures, REOs, estate sales, and familial transfers are invalid comps. Users must have the ability to flag/reject these.
3.  **The "Three S's" (Similarity, Size, Situs):** Our similarity scoring must explicitly reflect these criteria, and the UI should explain *why* a comp received a specific grade based on these dimensions.

## User Experience (UX) Workflow
1.  **Phase 1: Pre-Discovery Confirmation:** User enters address. System retrieves official subject data. User must explicitly confirm this data (Sqft, Beds, Baths, Year Built) is correct *before* the market search begins, as this anchors the search.
2.  **Phase 2: Discovery & Grading:** The system fetches sales and calculates a preliminary "Similarity Grade" (A, B, C, F) based on the Three S's and Valuation Date proximity. *No final market value is shown yet.*
3.  **Phase 3: Human Review & Curation:** The user is presented with a "Comp Curation" dashboard.
    *   **Ranking:** Comps are sorted by grade.
    *   **Review:** User reviews each comp's details and Arms-Length probability.
    *   **Rejection:** User can reject comps with specific, recorded reasons (e.g., "Non-arms-length," "Different neighborhood," "Poor condition").
    *   **Selection:** User must explicitly "Select" or "Pin" the 3-5 best comps.
4.  **Phase 4: Final Valuation & Report:** Only after the user confirms their comp selection does the system run the final Reconciled Value math (applying dollar adjustments) and reveal the suggested grievance value and PDF report.

## Functional Requirements
- **Documentation Sync:** Ensure `grievance_mcp_design.md` and `conductor/product.md` reflect this new two-step (Curate -> Calculate) workflow.
- **Grading Engine:** Update `calculate_similarity` in `src/app/core.py` to output a clear Letter Grade and weigh the sale date against the NYS Valuation Date.
- **Database Schema:** Add `rejection_reason`, `is_selected`, and `grade` to the `sales_comps` table.
- **Workflow State:** Update `src/main.py` and templates to support the distinct "Curation" view vs the "Final Report" view.

## Technical Standards
- Maintain 100% test coverage for new grading and selection logic.
- Ensure all API endpoints are idempotent where possible.
- The generated RP-524 and Methodology PDF must explicitly mention the Valuation Date and the Arms-Length verification performed by the user.
