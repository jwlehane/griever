# Implementation Plan: Comp Refinement Workflow & Documentation Sync

## Phase 1: Documentation & Product Alignment
- [x] Task: Update `grievance_mcp_design.md` to reflect current FastAPI + Multi-County architecture.
- [x] Task: Update `conductor/product.md` and `conductor/tech-stack.md` with PDF and Ulster support details.

## Phase 2: Enhanced Comp Management (Backend)
- [ ] Task: Add `rejection_reason` and `is_pinned` columns to `sales_comps` table in `src/app/core.py`.
- [ ] Task: Refactor `calculate_valuation` to prioritize `is_pinned` comps and support manual selection.
- [ ] Task: Implement `@app.post("/select_comp")` and `@app.post("/unselect_comp")` in `src/main.py`.
- [ ] Task: Update `reject_comp` endpoint to accept an optional `reason` string.

## Phase 3: UI Improvements (Frontend)
- [ ] Task: Update `src/templates/report.html` to show "Used" vs "Available" sections more clearly.
- [ ] Task: Add "Use this Comp" (Pin) button to available comps.
- [ ] Task: Add "Rejection Reason" modal/prompt when clicking Reject.
- [ ] Task: Implement "Pre-Discovery confirmation" UI on the index page (summary of subject specs before search).

## Phase 4: Validation & Cleanup
- [ ] Task: Add unit tests for pinned comp valuation logic.
- [ ] Task: Verify PDF generation includes pinned/manually selected comps correctly.
- [ ] Task: Final review and documentation of the new workflow.
