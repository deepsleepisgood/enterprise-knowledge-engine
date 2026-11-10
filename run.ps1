# One command for the whole app: database, API, worker and web app. Ctrl+C stops everything.
#   .\run.ps1                 # opens http://localhost:3000 when ready
#   .\run.ps1 --no-browser    # also: --no-worker
& "$PSScriptRoot\.venv\Scripts\python.exe" "$PSScriptRoot\scripts\run_app.py" @args
exit $LASTEXITCODE
