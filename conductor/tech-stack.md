# Tech Stack: Property Tax Grievance MCP Pipeline

## Orchestration
- **Gemini CLI (gcli):** Primary orchestrator using MCP servers.

## MCP Servers
- **Filesystem MCP:** For reading/writing local files and drafting documents.
- **SQLite MCP:** For data storage, normalization, and valuation math.
- **Cloud Run MCP:** For potential deployment of the service.

## Languages & Tools
- **Python 3.11:** For the virtual environment, data processing scripts, and potential API wrapper.
- **Bash/cURL:** For RapidAPI and ParcelAccess direct API requests.
- **Node.js/npm:** For running MCP servers.
- **SQLite:** Database `grievance_data.db`.

## External APIs
- **RapidAPI (Real-Time Real-Estate Data):** Source for recent sales comps.
- **Dutchess County ParcelAccess:** Direct ASP API endpoints for official property records.
- **Google Cloud Run:** Targeted hosting platform for the final service.
