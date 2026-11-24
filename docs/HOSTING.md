# Hosting for free: GitHub Actions + Neon

The bot runs once an hour on GitHub's free runners and keeps its data in a free Neon Postgres.
Your laptop can be off. Everything stays in shadow mode, so no Kalshi keys go to GitHub.

**Free limits (checked 2026-11-23):**
- **GitHub Free, private repo:** $12 of compute a month, about 2,000 Linux minutes. One run an hour uses roughly 1,000–1,500.
- **Neon Free:** 1 GB storage, 100 compute-hours a month, sleeps after 5 idle minutes, never paused for inactivity.
- **Scheduled runs:** GitHub may delay them at busy times, and under heavy load may drop some. A late run is harmless
  (freshness checks stop the bot from trading on stale data). It just means fewer decisions that hour.

## 1. Create the database (Neon)

1. Sign up at https://neon.com and create a project. Pick a US East region, which is close to GitHub's runners.
2. On the project dashboard, open **Connect** and copy the connection string. It looks like
   `postgresql://USER:PASSWORD@ep-....neon.tech/neondb?sslmode=require`.
   Keep it private: it's the database password.

## 2. Create the private GitHub repo and push

1. On GitHub, **New repository**, name it e.g. `kalshi-forecaster`, set it to **Private**, and add no README.
2. Tell Claude the repo URL, or push it yourself:

```powershell
git remote add origin https://github.com/<you>/kalshi-forecaster.git
```

```powershell
git push -u origin main
```

`.env`, `Keys/`, `data/backtest/` and `logs/` are gitignored and never pushed.

## 3. Give the workflow the database

In the repo, go to **Settings → Secrets and variables → Actions → New repository secret**:
- Name: `DATABASE_URL`
- Value: the Neon connection string from step 1. The `postgresql://` form works as-is.

## 4. Copy the existing track record to Neon (optional but recommended)

This copies everything recorded locally so far (forecasts, shadow trades, positions). Run it **before** the first
hosted run, while Docker is up. Paste your Neon connection string in place of the placeholder:

```powershell
docker exec -e NEON_URL="<your Neon connection string>" trading-bot-db-1 sh -c 'pg_dump -U kalshi -d kalshi --no-owner --no-acl | psql "$NEON_URL"'
```

## 5. Start it

In the repo, open **Actions → shadow → Run workflow**. Check the run log: it ends with the report. After that it
runs every hour on its own.

## 6. Stop the local copy

Once a hosted run has succeeded, stop the laptop scheduler so two copies don't trade the same account
(they would write to different databases, but only one record should count):

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*app.jobs.schedule*' } | ForEach-Object { Stop-Process -Id $_.ProcessId }
```

## Storage

Neon's free tier caps storage at 1 GB. The hourly retention step deletes snapshots older than 14 days that no
forecast or trade referenced, and empties raw weather responses after 7 days (the parsed values stay). Anything a
decision used is kept forever.

## Hourly trigger (cron-job.org)
GitHub's built-in `schedule:` never fired for this repo, so a free cron-job.org job starts each run instead
(set up 2026-11-24).
- **Token:** a fine-grained personal access token. It has access only to `kalshi-forecaster`, with Actions:
  Read and write and nothing else. It expires 2027-02-22, so renew it before then and paste the new one into the job.
- **Job:** every hour. `POST https://api.github.com/repos/Milol0608/kalshi-forecaster/actions/workflows/shadow.yml/dispatches`,
  body `{"ref":"main"}`, headers `Authorization: Bearer <token>`, `Accept: application/vnd.github+json`,
  `X-GitHub-Api-Version: 2026-03-10`, `Content-Type: application/json`. Success is `200`.
- **Failure emails** are on. cron-job.org disables a job after 25 failures in a row.
- **The report's RUNS section** shows how many of the last 24 hours had a run, and flags any gap over 2 h.
- If the token might have leaked, delete it on GitHub (Settings → Developer settings → Fine-grained tokens) and
  make a new one. cron-job.org may store request headers unencrypted, which is why the token can only start runs.
