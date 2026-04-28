# Property Tax Grievance MCP Pipeline

## Objective
Automate local market data retrieval and valuation adjustments using Gemini CLI configured with Model Context Protocol (MCP) servers. This system relies on the CLI to orchestrate data flows, minimizing manual Python scripts.

## Tech Stack
* **Environment:** `bot-envy` Python virtual environment.
* **Orchestrator:** Gemini CLI (`gcli`).
* **Storage:** SQLite (managed via MCP).
* **Web Scraping:** Playwright (managed via MCP).
* **File Operations:** Local Filesystem (managed via MCP).
* **External Data:** RapidAPI (Real-Time Real-Estate Data) accessed via shell `curl`.

## Pipeline Architecture
1.  **Discovery (Shell/cURL):** The CLI executes `curl` requests to RapidAPI to fetch recent 3-4 bedroom sales in Rhinebeck. The JSON response is piped directly into the CLI's context.
2.  **Verification (Playwright MCP):** For 67 N Parsonage St, 33 Cedar Heights, and the discovered comps, the CLI uses the Playwright MCP to navigate Dutchess County ParcelAccess. It extracts the official 2026 assessed value, SBL number, and square footage.
3.  **Structuring & Storage (SQLite MCP):** The CLI parses the RapidAPI and ParcelAccess data, formats it, and uses the SQLite MCP to create a local database (`grievance_data.db`), inserting the normalized records.
4.  **Valuation Math (SQLite MCP):** The CLI runs SQL queries to calculate "Reconciled Value." It applies standard appraisal math (e.g., deducting value for variance in bathroom count or acreage) directly within the database.
5.  **Document Generation (Filesystem MCP):** The CLI extracts the top 3 adjusted comps from SQLite and uses the Filesystem MCP to draft the narrative arguments for Form RP-524 directly to local Markdown files.

## GCLI Configuration Notes
The Gemini CLI needs the servers mapped in its configuration file. The setup script outputs the JSON block to append for the Filesystem, SQLite, and Playwright servers.
