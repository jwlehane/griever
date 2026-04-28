#!/bin/bash

# Setup script for property tax grievance MCP pipeline
# Run this from your terminal in Antigravity

echo "Setting up dedicated environment for MCP..."

# 1. Ensure Node.js and npm are installed (required for standard MCP servers)
if ! command -v npm &> /dev/null; then
    echo "npm not found. Please install Node.js first."
    exit 1
fi

# 2. Create and activate a clean, stable virtual environment
echo "Creating virtual environment 'tax-grieve-env'..."
python3 -m venv tax-grieve-env
source tax-grieve-env/bin/activate

# 3. Install Python dependencies
pip install --upgrade pip
pip install requests

# 4. Install standard MCP servers globally via npm
echo "Installing MCP servers..."
npm install -g @modelcontextprotocol/server-playwright
npm install -g @modelcontextprotocol/server-sqlite
npm install -g @modelcontextprotocol/server-filesystem

# 5. Setup Playwright browsers
npx playwright install chromium

# 6. Initialize local SQLite database file
touch grievance_data.db

echo "Setup complete."
echo "----------------------------------------------------"
echo "To attach these to Gemini CLI, add this to your gcli config JSON:"
echo ""
echo '{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "./"]
    },
    "sqlite": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-sqlite", "grievance_data.db"]
    },
    "playwright": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-playwright"]
    }
  }
}'
echo "----------------------------------------------------"