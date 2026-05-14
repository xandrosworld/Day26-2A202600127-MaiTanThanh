# Database MCP Server with FastMCP and SQLite

Student: Mai Tấn Thành
MSV: 2A202600127

This repository is a complete Day 26 Track 3 lab submission. It implements a local Model Context Protocol server with FastMCP and SQLite, exposes three validated database tools, publishes schema resources, and includes repeatable tests plus client configuration examples.

## Features

- FastMCP server over stdio by default
- Local SQLite database with reproducible schema and seed data
- Exactly three MCP tools: `search`, `insert`, `aggregate`
- MCP resources:
  - `schema://database`
  - `schema://table/{table_name}`
- Safe validation for table names, column names, filter operators, aggregates, limits, offsets, and empty inserts
- Parameterized SQL values, with validated and quoted identifiers
- Tool annotations for client trust hints: `search` and `aggregate` are read-only, `insert` is non-idempotent
- Bonus HTTP/SSE bearer-token auth for remote transports
- Bonus optional PostgreSQL adapter behind the same MCP tool/resource surface
- Repeatable pytest suite and verification script
- Ready-to-use local configs for Claude Code, VS Code MCP, Codex, Gemini CLI, and MCP Inspector

## Project Structure

```text
implementation/
  db.py                 # SQLite adapter, validation, safe SQL building
  init_db.py            # Reproducible schema and seed data
  mcp_server.py         # FastMCP tools and resources
  postgres_db.py        # Optional PostgreSQL adapter for bonus backend support
  verify_server.py      # Repeatable MCP client verification
  verify_http_auth.py   # HTTP bearer auth verification
  start_inspector.ps1   # Windows helper for MCP Inspector
  start_inspector.sh    # Bash helper for MCP Inspector
  tests/
    test_bonus.py
    test_db.py
    test_mcp_server.py
client_configs/
  claude.mcp.example.json
  codex.config.example.toml
  gemini.mcp.example.json
client_runs/
  codex_mcp_smoke.txt
  http_auth_smoke.txt
```

## Setup

PowerShell commands from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe implementation\init_db.py --reset
```

The database is created at:

```text
implementation/data/lab.sqlite3
```

The server also creates the database automatically on first start if it is missing.

## Run Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Verified locally:

```text
16 passed
```

## Run Verification Script

```powershell
.\.venv\Scripts\python.exe implementation\verify_server.py
```

Expected output includes:

```text
PASS: exactly search, insert, aggregate tools are discoverable
PASS: schema://database resource is discoverable
PASS: schema://table/{table_name} resource template is discoverable
PASS: full schema resource is readable
PASS: single table schema resource is readable
PASS: valid search call returns ordered rows
PASS: valid insert call returns inserted payload with generated id
PASS: valid aggregate call returns grouped metrics
PASS: invalid tool call returns a clear MCP error
All verification checks passed.
```

HTTP bearer-auth verification:

```powershell
.\.venv\Scripts\python.exe implementation\verify_http_auth.py
```

Expected output:

```text
PASS: HTTP MCP server starts with bearer auth enabled
PASS: missing bearer token is rejected
PASS: wrong bearer token is rejected
PASS: valid bearer token can discover tools and call aggregate
HTTP auth verification passed.
```

Saved proof:

```text
client_runs/http_auth_smoke.txt
```

## Run MCP Server

Default stdio transport:

```powershell
.\.venv\Scripts\python.exe implementation\mcp_server.py
```

Optional HTTP transport for local experiments:

```powershell
.\.venv\Scripts\python.exe implementation\mcp_server.py --transport http --host 127.0.0.1 --port 8000
```

Authenticated HTTP transport for bonus demo:

```powershell
.\.venv\Scripts\python.exe implementation\mcp_server.py --transport http --host 127.0.0.1 --port 8000 --auth-token sqlite-lab-demo-token
```

Clients should connect to:

```text
http://127.0.0.1:8000/mcp
```

With bearer token:

```text
sqlite-lab-demo-token
```

Use a custom database path:

```powershell
.\.venv\Scripts\python.exe implementation\mcp_server.py --db-path C:\path\to\lab.sqlite3
```

Or set:

```powershell
$env:SQLITE_LAB_DB_PATH = "C:\path\to\lab.sqlite3"
```

## Optional PostgreSQL Backend

SQLite is the default implementation used by the tests and demo. The server also includes an optional PostgreSQL adapter using the same MCP tools and resources.

Install optional dependency:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-postgres.txt
```

Run against PostgreSQL:

```powershell
.\.venv\Scripts\python.exe implementation\mcp_server.py --backend postgres --postgres-dsn "postgresql://user:password@localhost:5432/lab" --postgres-schema public
```

Or use environment variables:

```powershell
$env:SQLITE_LAB_BACKEND = "postgres"
$env:POSTGRES_DSN = "postgresql://user:password@localhost:5432/lab"
$env:POSTGRES_SCHEMA = "public"
.\.venv\Scripts\python.exe implementation\mcp_server.py
```

This is optional bonus support. The base lab remains fully reproducible with SQLite and no external database server.

## Tool Reference

### `search`

Search rows with optional selected columns, filters, ordering, limit, and offset.

Example arguments:

```json
{
  "table": "students",
  "filters": {"cohort": "A1"},
  "columns": ["student_code", "name", "cohort", "gpa"],
  "order_by": "gpa",
  "descending": true,
  "limit": 3,
  "offset": 0
}
```

Supported filter forms:

```json
{"cohort": "A1"}
```

```json
{"gpa": {"op": ">=", "value": 3.5}}
```

```json
[
  {"column": "cohort", "op": "=", "value": "A1"},
  {"column": "gpa", "op": ">=", "value": 3.5}
]
```

Supported operators: `=`, `!=`, `>`, `>=`, `<`, `<=`, `like`, `contains`, `startswith`, `endswith`, `in`, `is_null`, `not_null`, plus aliases such as `eq`, `ne`, `gt`, `gte`, `lt`, `lte`.

### `insert`

Insert one row or a list of rows. Empty inserts and unknown columns are rejected.

Example arguments:

```json
{
  "table": "students",
  "values": {
    "student_code": "2A202699999",
    "name": "Demo Student",
    "cohort": "A3",
    "email": "demo.student@example.edu",
    "gpa": 3.51
  }
}
```

### `aggregate`

Run `count`, `avg`, `sum`, `min`, or `max` with optional filters and grouping.

Example arguments:

```json
{
  "table": "students",
  "metric": "avg",
  "column": "gpa",
  "group_by": "cohort"
}
```

Count rows:

```json
{
  "table": "students",
  "metric": "count"
}
```

## Resource Reference

Full schema:

```text
schema://database
```

Single table schema:

```text
schema://table/students
schema://table/courses
schema://table/enrollments
```

Each resource returns JSON with table names, columns, primary keys, foreign keys, and row counts.

## Client Setup Examples

First get absolute paths:

```powershell
$PYTHON = (Resolve-Path .\.venv\Scripts\python.exe).Path
$SERVER = (Resolve-Path .\implementation\mcp_server.py).Path
```

### MCP Inspector

```powershell
npx -y @modelcontextprotocol/inspector $PYTHON $SERVER
```

Or:

```powershell
.\implementation\start_inspector.ps1
```

Inspector checklist:

- Tools tab shows `search`, `insert`, `aggregate`
- Resources tab shows `schema://database`
- Resource templates show `schema://table/{table_name}`
- Valid calls return rows or aggregate values
- Invalid calls return clear errors

### Codex

This machine is already configured for Codex / VS Code Codex:

```powershell
codex mcp list
```

Expected server:

```text
sqlite_lab  C:\Users\DELL\Desktop\test\day26\.venv\Scripts\python.exe  C:\Users\DELL\Desktop\test\day26\implementation\mcp_server.py  enabled
```

The actual global config entry in `~/.codex/config.toml` is:

```toml
[mcp_servers.sqlite_lab]
command = 'C:\Users\DELL\Desktop\test\day26\.venv\Scripts\python.exe'
args = ['C:\Users\DELL\Desktop\test\day26\implementation\mcp_server.py']
```

Portable example for another machine:

```toml
[mcp_servers.sqlite_lab]
command = "C:\\ABSOLUTE\\PATH\\TO\\day26\\.venv\\Scripts\\python.exe"
args = ["C:\\ABSOLUTE\\PATH\\TO\\day26\\implementation\\mcp_server.py"]
```

An editable example is included at:

```text
client_configs/codex.config.example.toml
```

Verified Codex smoke test:

```powershell
codex exec --ephemeral -C . --dangerously-bypass-approvals-and-sandbox --output-last-message client_runs\codex_mcp_smoke.txt "Do not edit files. Use the sqlite_lab MCP server, not direct SQLite or shell, to read schema://table/students and then call the search tool for the top 1 student in cohort A1 ordered by gpa descending. Final answer must mention that the MCP server was used, list the students table columns, and give the top student's name and GPA."
```

Saved proof:

```text
client_runs/codex_mcp_smoke.txt
```

Smoke test result:

```text
Used the sqlite_lab MCP server for both the schema read and the student lookup.
Students table columns: id, student_code, name, cohort, email, gpa, created_at.
Top student in cohort A1 by GPA: An Nguyen, GPA 3.86.
```

### VS Code MCP

A ready-to-use project config is included:

```text
.vscode/mcp.json
```

It points to the local virtual environment and server script:

```json
{
  "servers": {
    "sqlite-lab": {
      "type": "stdio",
      "command": "C:\\Users\\DELL\\Desktop\\test\\day26\\.venv\\Scripts\\python.exe",
      "args": [
        "C:\\Users\\DELL\\Desktop\\test\\day26\\implementation\\mcp_server.py"
      ]
    }
  }
}
```

### Claude Code

Claude Code uses `.mcp.json`. This repository already includes a ready-to-use local `.mcp.json`:

```json
{
  "mcpServers": {
    "sqlite-lab": {
      "type": "stdio",
      "command": "C:\\Users\\DELL\\Desktop\\test\\day26\\.venv\\Scripts\\python.exe",
      "args": [
        "C:\\Users\\DELL\\Desktop\\test\\day26\\implementation\\mcp_server.py"
      ],
      "env": {}
    }
  }
}
```

Claude Code was not installed in PATH on this machine during verification, but the project-level config is ready. An editable portable example is included at:

```text
client_configs/claude.mcp.example.json
```

### Gemini CLI

Recommended command shape:

```powershell
gemini mcp add sqlite-lab $PYTHON $SERVER --description "SQLite lab FastMCP server" --timeout 10000
gemini mcp list
```

Suggested smoke prompt:

```powershell
gemini --allowed-mcp-server-names sqlite-lab --yolo -p "Use the sqlite-lab MCP server. Search the top 2 students in cohort A1 by GPA, then read schema://table/students."
```

An editable JSON example is included at:

```text
client_configs/gemini.mcp.example.json
```

## Demo Script

Use this sequence for a short two- to three-minute demo:

1. Run `python -m pytest` and show all tests pass.
2. Run `python implementation/verify_server.py` and show discovery, resource, valid call, and invalid call checks pass.
3. Run `python implementation/verify_http_auth.py` and show missing/wrong bearer tokens are rejected.
4. Open MCP Inspector with `.\implementation\start_inspector.ps1`.
5. Show the three tools: `search`, `insert`, `aggregate`.
6. Read `schema://database` and `schema://table/students`.
7. Call `search` for cohort `A1`, ordered by `gpa` descending.
8. Call `insert` to add a demo student.
9. Call `aggregate` with average `gpa` grouped by `cohort`.
10. Call `search` with a missing table name and show the clear validation error.
11. Show `codex mcp list`, then open `client_runs/codex_mcp_smoke.txt` as proof that Codex used the MCP server.
12. Open `client_runs/http_auth_smoke.txt` as proof of the HTTP auth bonus.

## Bonus Coverage

- HTTP auth bonus: implemented with FastMCP `StaticTokenVerifier`, enabled by `--auth-token`, verified by `implementation/verify_http_auth.py`.
- PostgreSQL backend bonus: implemented in `implementation/postgres_db.py` behind `--backend postgres` with the same `search`, `insert`, `aggregate`, and schema resource surface.
- Extra polish: pagination limits, tool annotations, repeatable verification scripts, local client configs, and saved Codex/HTTP proof files.

## Safety Notes

The implementation does not concatenate raw user input into SQL. User-provided table and column names must match the live database schema before they are quoted into SQL. Values are passed through database parameters. Invalid table names, column names, filter operators, aggregate requests, pagination values, and empty inserts are rejected before execution.
