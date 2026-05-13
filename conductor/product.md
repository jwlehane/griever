# Product Definition: Property Tax Grievance Pipeline

## Overview
An automated pipeline for retrieving local market data and calculating property valuation adjustments for tax grievances. The system is a Python/FastAPI web application that handles data flows, analysis, and presents a user-friendly interface for generating defensible evidence for NYS assessment challenges.

## Core Goals
1. **End-to-End Automation:** Build a unified pipeline where entering an address triggers a full workflow: Discovery -> Verification -> Valuation -> Suggestion -> Narrative.
2. **Intelligent Suggestion Engine:** Multi-factor similarity scoring (Sqft, Age, Distance) and automated outlier detection to refine comp sets. Includes support for "Effective Age" adjustments and property condition factors.
3. **Official API Integration:** Direct integration with County ParcelAccess APIs (Dutchess, Ulster) for real-time verification against official RPS records.
4. **Professional Output:** Automated generation of filled RP-524 forms and comprehensive evidence packages in PDF format, suitable for submission to municipal Boards of Assessment Review (BAR).
5. **Human-in-the-Loop:** A web interface that allows users to review, reject, and manually add comparables to refine the automated estimate.
6. **Scalable Architecture:** Designed with a Multi-County architecture using the Factory pattern, allowing easy expansion to additional NYS counties.

## Key Features
- **Multi-County Support:** Specialized handlers for Dutchess and Ulster counties.
- **Equalization Rate Integration:** Automated lookup of 2025 RAR/ER values to derive implied market values.
- **Live Discovery:** Streaming progress updates during market search and verification.
- **PDF Evidence Package:** High-quality, print-ready documents for grievance filings.
- **BAR Info Integration:** Municipality-specific filing deadlines and contact information.

## Target Use Case
Property owners in Dutchess and Ulster counties looking to automate the gathering of comparable sales and the calculation of "fair market value" to challenge unfair property tax assessments.
