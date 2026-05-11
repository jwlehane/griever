# Implementation Plan: Renovations, Multi-County Architecture & Error Reporting

## Phase 1: Robust Error Handling & Admin Reporting
- [x] Task: Implement a global FastAPI exception handler in `src/main.py`.
- [x] Task: Create a utility in `src/app/utils.py` for dispatching email error reports to `jwlehane@gmail.com`.
- [x] Task: Update API client logic to include retry decorators and specific handling for "API changed/broken" scenarios (e.g., parsing errors).

## Phase 2: Multi-County Architectural Isolation
- [x] Task: Create `src/app/counties/base.py` defining the `CountyInterface` abstract base class.
- [x] Task: Migrate existing Dutchess County scraping/API logic from `src/app/core.py` to `src/app/counties/dutchess.py`.
- [x] Task: Implement a `CountyFactory` in `src/app/counties/factory.py` to route requests based on address/zip.
- [x] Task: Refactor `src/app/core.py` to use the `CountyFactory` for all verification and profile tasks.

## Phase 3: Renovation & Effective Age Logic
- [x] Task: Update `src/templates/report.html` to include a "Significant Renovation?" toggle/prompt.
- [x] Task: Add support for `renovation_year` in `src/main.py`.
- [x] Task: Implement `calculate_effective_year_built(original, renovation)` in `src/app/core.py`.
- [x] Task: Update `calculate_similarity` and `calculate_valuation` to use the `effective_year_built` if provided.

## Phase 4: Validation
- [x] Task: Add unit tests for the `CountyFactory` and `effective_age` math.
- [x] Task: Manually verify the "Error Report" email functionality by triggering a mock failure. (Console logs verified).
