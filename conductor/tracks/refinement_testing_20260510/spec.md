# Specification: Refine Automated Discovery & Valuation with Robust Testing

## Overview
This track focuses on elevating the property tax grievance pipeline from a basic prototype to a robust, production-ready system. It introduces intelligent comp selection via similarity scoring, error-resistant valuation via outlier detection, and a dual-layer testing strategy (automated & human) as requested by the user.

## Goals
1. **Intelligent Discovery**: Rank automated search results using a multi-factor similarity score (Distance, Sqft, Age).
2. **Accurate Valuation**: Filter out statistically improbable comps (outliers) to ensure a strong legal case.
3. **Robust Testing**: 
    - **Automated**: Unit tests for scoring and math; integration tests for the full flow.
    - **Human**: A dedicated review step in the UI to manually verify and curate the discovery results.

## Technical Changes
- **`tools/discover_sales.py`**: Add `calculate_similarity(subject, comp)` function.
- **`tools/calculate_valuation.py`**: Add `filter_outliers(comps, threshold=0.25)` logic.
- **`src/app/core.py`**: Integrate scoring and filtering into the main pipeline.
- **`src/templates/report.html`**: Add "Comp Quality" score visualization and "Reject" buttons.
- **`tests/`**: Create `test_discovery.py` and `test_valuation.py`.

## Success Criteria
- [ ] 100% test pass rate on valuation math.
- [ ] Automated discovery results are ranked by similarity score.
- [ ] Valuation report successfully identifies and suggests removal of outliers (>25% deviance).
- [ ] Pipeline runs successfully against the updated May 2026 parcel database.
