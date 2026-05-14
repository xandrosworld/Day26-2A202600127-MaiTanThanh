#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ -z "${PYTHON_BIN:-}" ]; then
  if [ -x "$REPO_DIR/.venv/bin/python" ]; then
    PYTHON_BIN="$REPO_DIR/.venv/bin/python"
  elif [ -x "$REPO_DIR/.venv/Scripts/python.exe" ]; then
    PYTHON_BIN="$REPO_DIR/.venv/Scripts/python.exe"
  else
    PYTHON_BIN="python"
  fi
fi

npx -y @modelcontextprotocol/inspector "$PYTHON_BIN" "$SCRIPT_DIR/mcp_server.py"
