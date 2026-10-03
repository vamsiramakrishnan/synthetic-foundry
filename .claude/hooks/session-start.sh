#!/bin/bash
# Install Worldloom into a Claude Code cloud session before the agent starts.
# `.mcp.json` launches `worldloom mcp`; without the console script on PATH the
# MCP server fails to connect and every agent loses its tools silently.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}"

# The same extras and tool pins as the CI lint job, so local gates reproduce CI.
pip install -q uv
uv pip install --system -q -e ".[dev,polars,xlsx,docx,pdf,pptx,mcp]" \
  ruff==0.15.8 mypy==2.3.1
