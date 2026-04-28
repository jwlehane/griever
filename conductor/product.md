# Product Definition: Property Tax Grievance MCP Pipeline

## Overview
An automated pipeline for retrieving local market data and calculating property valuation adjustments for tax grievances. The system uses the Gemini CLI with MCP servers to orchestrate data flows and analysis.

## Core Goals
1. **Automated Discovery:** Fetch recent real estate sales data via RapidAPI.
2. **Data Verification:** Extract official property data from Dutchess County ParcelAccess using Playwright.
3. **Normalized Storage:** Store and query data in a local SQLite database.
4. **Valuation Analysis:** Perform appraisal math (adjustments for bedrooms, bathrooms, acreage) within SQLite.
5. **Narrative Generation:** Draft grievance arguments (Form RP-524) in Markdown.

## Target Use Case
Property owners or representatives in Rhinebeck/Dutchess County looking to automate the gathering of comparable sales and the calculation of "fair market value" for tax assessment challenges.
