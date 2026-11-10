@echo off
rem One command for the whole app: database, API, worker and web app. Ctrl+C stops everything.
rem Options: --no-browser  --no-worker
"%~dp0.venv\Scripts\python.exe" "%~dp0scripts\run_app.py" %*
