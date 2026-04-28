# Tech Stack: Property Tax Grievance MCP Pipeline

## Orchestration
- **Gemini CLI (gcli):** Primary orchestrator using MCP servers.

## MCP Servers
- **Filesystem MCP:** For reading/writing local files and drafting documents.
- **SQLite MCP:** For data storage, normalization, and valuation math.
- **Playwright MCP:** For web scraping ParcelAccess data.

## Languages & Tools
- **Python 3.11:** For the virtual environment and potential helper scripts.
- **Bash/cURL:** For RapidAPI discovery requests.
- **Node.js/npm:** For running MCP servers.
- **SQLite:** Local database file `grievance_data.db`.

## External APIs
- **RapidAPI (Real-Time Real-Estate Data):** Source for recent sales comps.
- **Dutchess County ParcelAccess:** Official source for property records.
