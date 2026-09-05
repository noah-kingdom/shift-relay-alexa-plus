$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Venv = Join-Path $Root ".venv-official-mcp"
$Evidence = Join-Path $Root "official-proof-evidence.json"
$Db = Join-Path $Root "official-proof-state.db"
$ServerOut = Join-Path $Root "OFFICIAL_MCP_SERVER_STDOUT.txt"
$ServerErr = Join-Path $Root "OFFICIAL_MCP_SERVER_STDERR.txt"
$ClientLog = Join-Path $Root "OFFICIAL_MCP_CLIENT_PROOF.jsonl"

if (!(Test-Path $Venv)) { python -m venv $Venv }
$Python = Join-Path $Venv "Scripts\python.exe"
& $Python -m pip install --upgrade pip
& $Python -m pip install "mcp>=1.28,<2" "fastapi>=0.115" "uvicorn>=0.30" "pytest>=8" "httpx>=0.27"

Remove-Item $Evidence,$Db,$ServerOut,$ServerErr,$ClientLog -ErrorAction SilentlyContinue
$env:PYTHONPATH = (Join-Path $Root "src")
$env:SHIFT_RELAY_DB = $Db
$env:SHIFT_RELAY_EVIDENCE_FILE = $Evidence

$Server = Start-Process -FilePath $Python -ArgumentList "-m","shift_relay.mcp_server" -PassThru -RedirectStandardOutput $ServerOut -RedirectStandardError $ServerErr
try {
    Start-Sleep -Seconds 3
    & $Python scripts\official_mcp_e2e.py --url http://127.0.0.1:8000/mcp --evidence-file $Evidence | Tee-Object -FilePath $ClientLog
    if ($LASTEXITCODE -ne 0) { throw "Official MCP proof client failed" }
    Write-Host "OFFICIAL MCP SDK E2E: PASS" -ForegroundColor Green
    Write-Host "Client proof: $ClientLog"
    Write-Host "Server stdout: $ServerOut"
    Write-Host "Server stderr: $ServerErr"
    Write-Host "Next visual certification: npx -y @modelcontextprotocol/inspector, connect to http://127.0.0.1:8000/mcp"
}
finally {
    if ($Server -and !$Server.HasExited) { Stop-Process -Id $Server.Id -Force }
}
