# CloudMaster local launcher (cloud-glass UI at /web/cloud-glass/)
# Real Qwen key lives in .env (gitignored); this script carries no key.
$here = $PSScriptRoot
if (-not $here) { $here = Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $here) { $here = (Get-Location).Path }
Set-Location $here
New-Item -ItemType Directory -Force -Path 'data\private' | Out-Null
Write-Host '[CloudMaster] starting (cloud-glass UI) ...'
Write-Host '  open  http://127.0.0.1:8000/web/cloud-glass/'
Write-Host '  stop  Ctrl+C'
& '.\\.venv\\Scripts\\python.exe' -m uvicorn cloudmaster.server:app --host 127.0.0.1 --port 8000