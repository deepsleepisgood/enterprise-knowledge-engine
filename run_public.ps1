# Serve the demo publicly from this machine (API + worker on Neon, Cloudflare tunnel, Vercel web).
& "$PSScriptRoot\.venv\Scripts\python.exe" "$PSScriptRoot\scripts\serve_public.py" @args
