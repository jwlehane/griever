# Product Definition: Property Tax Grievance MCP Pipeline

## Overview
An automated pipeline for retrieving local market data and calculating property valuation adjustments for tax grievances. The system uses the Gemini CLI with MCP servers to orchestrate data flows and analysis.

## Core Goals
1. **End-to-End Automation Tool:** Build a unified pipeline where entering an address triggers a full workflow: Discovery -> Verification -> Valuation -> Suggestion -> Narrative.
2. **Intelligent Suggestion Engine:** Multi-factor similarity scoring (Sqft, Age, Distance) and automated outlier detection to refine comp sets and ensure a defensible valuation.
3. **Robust Testing Framework:** Comprehensive automated unit and integration tests combined with human-in-the-loop verification steps.
4. **Web-Based Interface:** A minimalist web frontend for address entry, live discovery tracking, and manual comp curation.
5. **Official API Integration:** Direct integration with Dutchess County ParcelAccess APIs for real-time verification against official records.
6. **Grievance Document Generation:** Professional output suitable for RP-524 filings, including formal narratives.

## Target Use Case
Property owners or representatives in Rhinebeck/Dutchess County looking to automate the gathering of comparable sales and the calculation of "fair market value" for tax assessment challenges.
