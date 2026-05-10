# Implementation Plan: Refine Automated Discovery & Valuation with Robust Testing

## Phase 1: Similarity Scoring (Automated Discovery)
- [ ] Task: Implement `calculate_similarity` in `src/app/core.py`. Factors: Sqft (40%), Year Built (30%), Acreage (20%), Distance (10%).
- [ ] Task: Update `tools/discover_sales.py` to sort results by similarity score before inserting into DB.
- [ ] Task: Update `sales_comps` table schema to include `similarity_score` column.

## Phase 2: Outlier Detection (Valuation Engine)
- [ ] Task: Implement `detect_outliers` in `tools/calculate_valuation.py`. Mark comps with >25% reconciled value variance from the mean.
- [ ] Task: Update `src/app/core.py` to flag outliers in the pipeline return data.

## Phase 3: Automated Testing Framework
- [ ] Task: Create `tests/test_discovery.py` to verify scoring logic with synthetic data.
- [ ] Task: Create `tests/test_integration.py` to run the full pipeline against a test SQLite database.
- [ ] Task: Implement a "Test Data Generator" script to simulate various property profiles.

## Phase 4: Human Verification & UI Refinement
- [ ] Task: Update `src/templates/report.html` to show similarity scores and highlight outliers.
- [ ] Task: Add a "Reject Comp" action that updates the database and refreshes the report.
- [ ] Task: Final verification against the new May 2026 Parcel Database.
