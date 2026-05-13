# Implementation Plan: Comp Refinement & NYS Best Practices Workflow

## Phase 1: Documentation & Product Alignment
- [x] Task: Update `grievance_mcp_design.md` to reflect current FastAPI + Multi-County architecture. 7aa3924
- [x] Task: Update `conductor/product.md` and `conductor/tech-stack.md` with PDF and Ulster support details. 7aa3924

## Phase 2: Enhanced Selection Logic & Schema (Backend)
- [x] Task: Update `sales_comps` table schema in `src/app/core.py` to include `rejection_reason`, `is_selected`, and `grade`.
- [x] Task: Implement `calculate_similarity_grade` in `src/app/core.py` incorporating the NYS Valuation Date rule and the "Three S's."
- [x] Task: Implement `@app.post("/select_comp")` and update `reject_comp` to accept mandatory reasons.
- [x] Task: Refactor `calculate_valuation` to *only* run on comps where `is_selected = 1`.

## Phase 3: Interactive Curation & Confirmation (Frontend)
- [ ] Task: Implement "Subject Data Verification" step on the index page before triggering discovery.
- [ ] Task: Create the "Comp Curation" view: displays discovered comps with Letter Grades and "Select/Reject" actions.
- [ ] Task: Implement the "Finalize Selection" action that triggers the valuation math and transitions to the report.
- [ ] Task: Update the report view to explain the grading logic and how it aligns with NYS best practices.

## Phase 4: Validation & PDF Enrichment
- [ ] Task: Add unit tests for the grading engine and selected-comp valuation logic.
- [ ] Task: Update PDF generation (`src/app/pdf_gen.py`) to explicitly state the Valuation Date and reference the user's manual selection process.
- [ ] Task: Final project-wide documentation sync.
