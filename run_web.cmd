@echo off
rem CloudMaster 本地启动（云朵玻璃 /web/cloud-glass/），绕过执行策略
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_web.ps1"
pause
