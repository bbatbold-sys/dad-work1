@echo off
cd /d "%~dp0"
start "" python server.py
timeout /t 2 >nul
start chrome "http://localhost:7500"
