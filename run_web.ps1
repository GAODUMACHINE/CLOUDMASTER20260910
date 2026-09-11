# CloudMaster 本地启动（视觉风格：云朵玻璃 /web/cloud-glass/）
# 真实 Qwen 密钥全部在 .env（gitignored）；本脚本不涉及任何密钥。
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here
New-Item -ItemType Directory -Force -Path "data\private" | Out-Null
Write-Host "[CloudMaster] 正在启动（云朵玻璃前端）..."
Write-Host "  打开 -> http://127.0.0.1:8000/web/cloud-glass/"
Write-Host "  停止 -> Ctrl+C"
& ".\.venv\Scripts\python.exe" -m uvicorn cloudmaster.server:app --host 127.0.0.1 --port 8000