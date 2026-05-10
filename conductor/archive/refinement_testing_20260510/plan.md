# Implementation Plan: Refine Automated Discovery & Valuation with Robust Testing

## Phase 1: Similarity Scoring (Automated Discovery)
- [x] Task: Implement `calculate_similarity` in `src/app/core.py`. Factors: Sqft (40%), Year Built (30%), Acreage (20%), Distance (10%).
- [x] Task: Update `tools/discover_sales.py` to sort results by similarity score before inserting into DB.
- [x] Task: Update `sales_comps` table schema to include `similarity_score` column.

## Phase 2: Outlier Detection (Valuation Engine)
- [x] Task: Implement `detect_outliers` in `tools/calculate_valuation.py`. Mark comps with >25% reconciled value variance from the mean.
- [x] Task: Update `src/app/core.py` to flag outliers in the pipeline return data.

## Phase 3: Automated Testing Framework
- [x] Task: Create `tests/test_discovery.py` to verify scoring logic with synthetic data.
- [x] Task: Create `tests/test_integration.py` to run the full pipeline against a test SQLite database.
- [x] Task: Implement a "Test Data Generator" script to simulate various property profiles.

## Phase 4: Human Verification & UI Refinement
- [x] Task: Update `src/templates/report.html` to show similarity scores and highlight outliers.
- [x] Task: Add a "Reject Comp" action that updates the database and refreshes the report.
- [x] Task: Final verification against the new May 2026 Parcel Database.
