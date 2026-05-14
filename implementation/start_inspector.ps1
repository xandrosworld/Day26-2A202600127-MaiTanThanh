param(
    [string]$Python = ""
)

if (-not $Python) {
    $LocalPython = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
    if (Test-Path $LocalPython) {
        $Python = (Resolve-Path $LocalPython).Path
    } else {
        $Python = "python"
    }
}

$Server = Join-Path $PSScriptRoot "mcp_server.py"
npx -y @modelcontextprotocol/inspector $Python $Server

