# Deployment Guide

**Current status: not hosted.** This project previously ran on Render
(backend) + Vercel (frontend); that backend service has been shut down to
stop the recurring cost. Running it locally (see [README.md](README.md) for
building the data warehouse from scratch, then [TESTING_GUIDE.md](TESTING_GUIDE.md)
for backend/frontend setup) is the supported path now.

The rest of this file is kept as a reference for anyone who wants to
self-host their own copy on Render or Railway -- it worked, and the steps
below are accurate -- but read the real, disclosed limitation in
[CLAUDE.md](CLAUDE.md)'s "Known constraint" note first: on Render's
cheapest disk-capable tier (Standard, 2GB RAM), several data-heavy Decision
Center endpoints hit in sequence within one warm process can exhaust memory
and crash it. Fine for solo/light use, not verified stable under real
concurrent traffic. Paid tiers with more RAM likely fix it but cost more --
this is exactly the tradeoff that made self-hosting not worth it for this
project's own budget.

Three separate pieces, deployed separately: **frontend** (Vercel), **backend
API** (Render or Railway), and the **automated data pipeline** (stays local,
deliberately -- see below).

---

## 0. Before deploying anything

Run this first -- catches config mistakes in seconds instead of after a
failed deploy attempt:

```
python scripts/check_deployment_readiness.py
```

Zero required installs beyond Python 3 itself. Exit code 0 means nothing
required is missing (warnings are informational, not blocking).

A GitHub Actions workflow (`.github/workflows/ci.yml`) runs this same
check, plus a real `npm run build` of the frontend, on every push once this
repo is on GitHub -- that build step in particular is worth watching
closely on its first run: it's the first time the frontend gets checked
against a real network-connected build environment, since local
verification this session was limited to syntax/bracket-matching without
network access to actually run `next build`.

- [ ] `ANTHROPIC_API_KEY` ready (never commit it -- goes into the host's env
      var / secrets system only)
- [ ] Know your `airline.duckdb` file size (`ls -lh Data/Warehouse/airline.duckdb`)
      -- you'll size a persistent disk against this
- [ ] Decide your rate limit numbers (`COPILOT_RATE_LIMIT_MAX` /
      `COPILOT_RATE_LIMIT_WINDOW_SECONDS`) -- defaults (12 requests/60s per
      IP) are a reasonable starting point, not a requirement

---

## 1. Backend API -- Render (optional, if you choose to self-host)

Render is the easier first deployment if you have no hosting experience --
straightforward Docker support, good docs. NOT actually free for this app
though: confirmed via a real deploy attempt that Render's free tier does
not support persistent disks at all ("disks are not supported for free
tier services"), and this service needs one for the warehouse file.
`render.yaml` is set to the `starter` plan (~$7/mo base + $0.25/GB/mo for
the disk, ~$9.50/mo total at the 10GB default) -- the cheapest plan that
actually works here.

### 1.0: Verify the container actually RUNS (not just builds)

`docker build` succeeding only confirms the image assembles -- it says
nothing about whether the server inside actually starts and serves
requests. Do this once, locally, before touching Render at all:

```powershell
docker run -p 8000:8000 -e ANTHROPIC_API_KEY=your_real_key -e AIRLINE_DUCKDB_PATH=/data/airline.duckdb -v "C:\path\to\Data\Warehouse:/data" airlines-app-test
```

Then, in a second terminal:
```powershell
python scripts\smoke_test.py http://127.0.0.1:8000
```

This hits `/api/data-health`, `/api/carriers`, `/api/airports`, and
`/api/routes` and reports real pass/fail with real response times --
deliberately skips `/api/copilot/chat` (costs real API money per call;
test that one manually, once, through the UI instead).

1. Push this repo to GitHub (Render deploys from a repo, not a zip upload).
2. In the Render dashboard: **New +** -> **Blueprint**, point it at the repo.
   Render reads `render.yaml` at the repo root and proposes the service.
3. Fill in the two env vars marked `sync: false` in `render.yaml` (Render
   will prompt for these): `ANTHROPIC_API_KEY` and `CORS_ALLOWED_ORIGINS`
   (leave the latter blank for now -- you'll set it in step 4, after the
   frontend has a real URL).
4. Deploy. Render builds the `Dockerfile` and starts the service.
5. **Upload the warehouse file to the persistent disk.** `render.yaml`
   provisions a 10GB disk mounted at `/data` -- resize it in the dashboard
   first if your real file is bigger. Render's dashboard has a shell/SSH
   feature for the service; use it (or Render's disk upload docs) to get
   `airline.duckdb` onto `/data/airline.duckdb`. This is a manual step --
   there's no way around uploading a large binary file once, some way,
   the first time.
6. Test directly: visit `https://<your-service>.onrender.com/api/data-health`
   in a browser. If this returns real JSON, the backend is live and reading
   the warehouse correctly. Do this BEFORE touching the frontend at all --
   isolates backend problems from frontend problems.

### Alternative: Railway

Same Dockerfile, no `render.yaml` needed -- Railway auto-detects the
Dockerfile at the repo root. In Railway's dashboard: new project from the
GitHub repo, add a Volume (their equivalent of Render's persistent disk,
same idea: mount path + size), set the same env vars listed in
`render.yaml` by hand in Railway's Variables tab. Railway has no free tier
but usage-based pricing that starts cheap. Reasonable alternative if
Render's free-tier cold-start (the service sleeps after inactivity, first
request after idle is slow) becomes annoying.

---

## 2. Frontend -- Vercel

### 2.0: Clean up a stray root-level lockfile first

A real build log showed a "multiple lockfiles" warning -- a
`package-lock.json` at the project root (not part of this repo's current
structure, likely left over from an earlier project layout) alongside the
real one in `frontend/`. This can confuse Next.js's -- and Vercel's --
root-directory detection. Remove it once:
```powershell
Remove-Item "C:\path\to\AirlinesApp\package-lock.json" -ErrorAction SilentlyContinue
```
`next.config.ts` now also explicitly pins `turbopack.root` as a
belt-and-suspenders fix, so this should be resolved even if the stray file
somehow comes back.

No other code changes needed -- confirmed the frontend already reads
`NEXT_PUBLIC_API_BASE_URL` everywhere instead of hardcoding a URL.

1. Push to GitHub if not already (same repo, Vercel deploys the `frontend/`
   subfolder).
2. In Vercel: **New Project**, import the repo, set **Root Directory** to
   `frontend`. Vercel auto-detects Next.js -- no other config needed.
3. Add the one environment variable: `NEXT_PUBLIC_API_BASE_URL` = your real
   backend URL from step 1.6 above (e.g. `https://airline-otp-api.onrender.com`).
4. Deploy.

---

## 3. Connect them

Go back to your backend host's env vars and set `CORS_ALLOWED_ORIGINS` to
your real Vercel URL (e.g. `https://your-app.vercel.app`) -- comma-separated
if you have multiple (a preview URL and a production URL, for instance).
Redeploy the backend for this to take effect. Without this step, the
deployed frontend can reach the internet fine but the backend will reject
its requests -- this is the single most common "it deployed but nothing
works" cause.

Test end to end: visit the real Vercel URL, click through a few pages,
specifically test Copilot (the most config-sensitive feature -- it's the
one that needs the API key, CORS, and the rate limiter all working
correctly at once).

---

## 4. The automated pipeline -- deliberately stays local

`pipeline/auto_update.py` needs a real headless Chrome session to check BTS
for new data. Most simple hosting tiers don't have a browser available, and
getting one working reliably in a constrained container is a genuinely
separate, harder problem than the rest of this deployment. Not solved here
on purpose -- bundling it into a first deployment risks the whole thing
stalling on the hardest 20%.

The monthly T-100 enrichment has its own isolated updater for the same reason:
run `python -m pipeline.auto_update_bts` locally. It checks Segment and Market
against the latest period actually loaded in DuckDB, records the result in
`Data/t100_pipeline_state.json`, reloads only the T-100 table when a verified
ZIP is available, and leaves the flight-level OTP table untouched.

**Keep running it locally** (Task Scheduler, as already set up). After each
successful local run, push the updated `airline.duckdb` to wherever the
backend's persistent disk lives (Render's dashboard file upload, or `scp`/
`rsync` if you set up direct disk access -- exact mechanism depends on which
host you picked). This keeps the deployed site's data fresh without solving
"run Selenium on a server," which can be tackled later as its own project.

---

## 5. Real, current gaps -- known, not hidden

- **Rate limiting is per-process, in-memory.** Fine for a single backend
  instance (the realistic starting point). If this ever scales to multiple
  backend processes, each enforces the limit independently -- the effective
  limit becomes (per-process limit x process count). Solving that properly
  needs a shared store (Redis, etc.) -- not built, since it's real
  infrastructure this doesn't need yet.
- **No auth on read-only analytics endpoints.** The warehouse-writing
  `/api/admin/check-for-updates` endpoint now requires `PIPELINE_ADMIN_TOKEN`
  in production and should be invoked only by a private operator/scheduler.
  Would matter if this ever needs to distinguish who's asking.
- **The persistent-disk warehouse upload is manual**, not automated. A
  scripted sync (steps 4 -> host) is a reasonable next improvement once the
  basic deployment is proven stable.
