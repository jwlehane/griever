# Specification: Implement Property Data Discovery and SQLite Normalization

## Objective
Automate the retrieval of comparable sales data from RapidAPI and verify property details via Dutchess County ParcelAccess (Direct API), then store the normalized data in SQLite.

## Scope
- **Discovery:** Use `tools/fetch_comps.sh` to get recently sold homes in Rhinebeck, NY.
- **Verification:** Use Direct API calls to extract SBL, assessed value, and physical characteristics (sqft, beds, baths) for the subject and comps.
- **Persistence:** Populate the `properties` and `sales_comps` tables in `grievance_data.db`.

## Success Criteria
- JSON output from RapidAPI is successfully parsed.
- Direct API calls successfully query ParcelAccess and extract required fields.
- SQLite database contains verified records for 1 subject property and at least 3 comps.
