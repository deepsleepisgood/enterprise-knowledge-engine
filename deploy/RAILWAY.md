# Deploying the API and worker on Railway

One Railway service runs the API and the background worker together (they share uploaded files on
one disk). The web app stays on Vercel and the database on Neon. Models: DeepSeek v4.1 on Isoquant,
as configured in your local `.env` (98.8% on the 160 questions, about $0.06 per full run).

What is in the repo for this: `Dockerfile`, `.dockerignore`, `railway.json` (Dockerfile build,
health check `/health`, restart on failure), `scripts/start_service.sh` (migrations, worker, API on
`$PORT`), `deploy/seed_blobs/` (the originals of the 16 documents already in Neon, so "Open
original" works), `scripts/railway_env.py`, `scripts/point_vercel.py`, `scripts/warm_demo.py`,
`deploy/demo_questions.txt`.

## 1. Before you start
- **Railway Hobby plan** ($5 a month, includes $5 of usage; card needed). The trial's 1 GB of
  memory is too small: the API and the worker each load the reranker, about 2.5–3 GB together.
  If Railway offers a usage limit, set it to $10.
- **Code on GitHub:** commit and push `main` with the files above.
- **Neon:** nothing to do. Same region as below (Singapore). About 12 of the free plan's 100
  compute hours were used by 15 Nov; a worker running until 18 Nov adds roughly 20–40.

## 2. Create the service (dashboard, about 15 minutes including the first build)
1. railway.com → **New Project → Deploy from GitHub repo** → allow Railway's GitHub app on
   `deepsleepisgood/enterprise-knowledge-engine` → pick it, branch `main`.
   Railway reads `railway.json` and builds the `Dockerfile`.
2. The service → **Settings**:
   - **Region:** Southeast Asia (Singapore), next to Neon.
   - **Networking → Generate Domain** (the app listens on Railway's `$PORT`). Copy the
     `https://….up.railway.app` address.
3. The service → **Volumes → New volume**, mount path `/data` (1 GB is plenty).
4. **Variables:** on your laptop run `python scripts/railway_env.py`. It writes
   `deploy/railway.env` (git-ignored; values never printed). Open it, copy everything, and paste
   it in the service → **Variables → Raw Editor → Update Variables**. Then delete the file.
5. **Deploy** (Railway redeploys after the variable change). The first build takes about
   10 minutes (Python packages and the two local models, ~1.2 GB). Wait for **Active**.
6. Open `https://<address>/health`: it should say `{"status":"ok","db":true}`.

## 3. Point the website at it
`python scripts/point_vercel.py https://<address>` (uses `VERCEL_TOKEN` from `.env`; about a
minute). Then open https://ps07-knowledge-engine.vercel.app and ask "What is the price
tolerance?": the answer should cite AP SOP v4.0.

## Several people at once (read before the load test)
- **Database connections:** each answer holds a connection for its whole run (model calls
  included) plus one for the parallel search. The API allows 40 (`DB_POOL_SIZE` 10 +
  `DB_MAX_OVERFLOW` 30) and works on 16 answers at once (`ASK_CONCURRENCY`); more wait their
  turn. `/health` shows `db_pool` (`in_use`, `idle`, `max`): if `in_use` sits at `max` under
  load, the pool is the limit, not Neon. Keep `DATABASE_URL` on Neon's `-pooler` address.
- **Model calls:** `NIM_MAX_RPM` / `NIM_MAX_CONCURRENT` throttle the whole server. The
  NVIDIA free-tier values (35 / 4) queue calls with more than a few users; set them to what the
  Isoquant account allows. With `LLM_PROVIDER=anthropic` these do not apply; check the
  account's limits in the Anthropic console instead.

## 4. Warm up, load test, rehearse
- `python scripts/warm_demo.py --base https://<address>`: asks the 8 demo questions once, so on
  stage they come from the cache. Rerun after any redeploy and on the demo morning.
- `python scripts/run_load_test.py --base https://<address> --levels 5,10 --per-user 2`
  (a few cents). Watch Railway → Metrics for memory.
- Rehearse in the order of `deploy/demo_questions.txt`, from another network (mobile data).
- Backup: `.\run_public.ps1` runs everything from the laptop through a tunnel and points Vercel
  at it. Afterwards point Vercel back with `point_vercel.py`.

## If something breaks
| Symptom | Do this |
|---|---|
| Answers never arrive | Railway → Deployments → logs. Not back in 2 minutes: switch to the backup. |
| `/health` says down or the service shows unhealthy | Restart the deployment (⋮ → Restart). If one process died without the container stopping, this brings both back. |
| "Out of memory" or restarts | Metrics; raise the memory limit (Hobby allows up to 8 GB). |
| Database errors | Ask again (Neon wakes in seconds); then check Neon usage. |
| Everything down | Play the recorded rehearsal. |

## Afterwards
Delete the Railway service to stop charges, or leave it running if the team wants it.
