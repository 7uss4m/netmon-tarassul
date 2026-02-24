# Netmon Tarassul

A **Syrian Telecom Self Portal** monitor: fetches your internet package usage from the telecom API, stores history, and notifies you via [ntfy](https://ntfy.sh) when usage hits 25%, 50%, 75%, 90%, or 100%.

## Features

- **Automatic fetches** — Daily baseline at 01:00 (for charts and daily usage; hidden from UI) and one configurable scheduled fetch (default 20:00)
- **Usage dashboard** — View current usage %, monthly volume, limit, and projected exceed day
- **History** — Per-month fetch history
- **ntfy alerts** — Push notifications at usage thresholds (in-memory dedup per process; no DB storage)
- **Protected web UI** — JWT-based login; admin username/password read from `data/netmon.conf`
- **SQLite storage** — `fetches` (scheduled + manual; shown in Records), `baseline_fetches` (daily 01:00; drives dashboard chart and daily usage). Settings and auth in `data/netmon.conf`.

> **Note:** Run this on a **local server** (e.g. at home). The Syrian Telecom API only accepts requests from Syrian IPs, so the app must run on a machine inside Syria (same network as your connection). Do not run it on a cloud/VPS abroad — fetches will fail.

## Prerequisites

- **Python 3.12+** (or use Docker)
- Syrian Telecom Self Portal credentials (username/password)

## Quick start with Docker

1. **Create the config file** (copy from example and edit):

   ```bash
   mkdir -p data
   cp data/netmon.conf.example data/netmon.conf
   # Edit data/netmon.conf: set JWT_SECRET, ADMIN_PASSWORD, Tarassul credentials, NTFY_URL, etc.
   ```

2. **Run the app**:

   ```bash
   docker compose up -d
   ```

Open **http://localhost:5000**. Login with `ADMIN_USERNAME` / `ADMIN_PASSWORD` from `data/netmon.conf`. Default username is **admin** if not set.

Data and config live in `./data/` (database: `./data/data.db`, config: `./data/netmon.conf`).

**Config file** (`data/netmon.conf`): same format as `.env` (KEY=VALUE, `#` comments). All options are optional; see `data/netmon.conf.example` for the list.

## Run locally (without Docker)

1. **Create a virtual environment and install dependencies** (from repo root)

   ```bash
   python -m venv .venv
   .venv\Scripts\activate   # Windows
   # source .venv/bin/activate   # Linux/macOS
   pip install -r requirements.txt
   ```

2. **Create the config file** (copy from example and edit):

   ```bash
   mkdir -p data
   cp data/netmon.conf.example data/netmon.conf
   # Edit data/netmon.conf with your JWT_SECRET, admin password, Tarassul credentials, etc. DB is always data/data.db.
   ```

   The app loads config from `data/netmon.conf` (project root = parent of `src/`). Same format as `.env` (KEY=VALUE). See `data/netmon.conf.example` for all keys.

3. **Start the app** (run from the **project root** so `data/netmon.conf` is found)

   ```bash
   python src/app.py
   ```

   Then open **http://localhost:5000**. Ensure `data/netmon.conf` exists (the app creates it from `data/netmon.conf.example` on first run if missing).

## Configuration

All app settings are in **`data/netmon.conf`** (KEY=VALUE format). The Settings page in the UI is read-only and shows current values; edit the file and restart the app to apply changes.

| Config key | Description |
|------------|-------------|
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | Dashboard login (read from config only) |
| `TARASSUL_BASE_URL` | Syrian Telecom Self Portal API URL |
| `TARASSUL_USERNAME` / `TARASSUL_PASSWORD` | Tarassul API credentials |
| `TARASSUL_FID` / `TARASSUL_LANG` | Portal F_ID (default `3`) and language |
| `ENABLE_SCHEDULE` | Enable scheduled fetch (`true` / `false`). When false, only manual "Fetch now" runs. |
| `FETCH_HOUR_2` | Scheduled fetch hour (0–23). Daily baseline runs at 01:00 (not configurable, hidden from UI) |
| `NTFY_URL` / `NTFY_TOKEN` | ntfy topic URL and optional auth token |
| `THEME` | UI theme: `dark` or `light` |

The **database** (`data/data.db`) has **fetches** (scheduled + manual; shown in Records), **baseline_fetches** (daily 01:00; used for dashboard chart and daily usage calc), and **notifications** (ntfy sent per threshold per month). ntfy is sent only on scheduled/manual fetch, not on baseline.

## API (all require JWT cookie)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/latest` | Latest fetch result |
| GET | `/api/history?month_begin=YYYY-MM-DD` | History for a billing month |
| POST | `/api/fetch` | Trigger a fetch now |
| GET | `/api/settings` | Read current config (from netmon.conf; read-only) |
| POST | `/api/settings/ntfy-test` | Send a test ntfy notification |
| POST | `/api/settings/password` | Change admin password in netmon.conf (JSON: `{"password": "new"}`; admin only) |

## Project layout

**Root (config / docs):**

| File | Purpose |
|------|--------|
| `README.md` | This file |
| `requirements.txt` | Python dependencies |
| `Dockerfile` | Container image build |
| `docker-compose.yml` | Run the app in Docker |

**`src/` (application):**

| File | Purpose |
|------|--------|
| `app.py` | Flask app: routes, JWT login, dashboard, API |
| `db.py` | SQLite schema, fetches, notifications |
| `fetcher.py` | Telecom API fetch, usage computation, ntfy notifications |
| `scheduler.py` | APScheduler: twice-daily fetch jobs |
| `templates/` | Login, dashboard, settings HTML |


## TODO

- [ ] Support extra internet packages in calculations  
  - [ ] Detect active extra/top-up packages from the Tarassul API response  
  - [ ] Store extra package quota/usage in the database (baseline + fetches)  
  - [ ] Adjust total limit and usage so charts, daily usage, and exceed-day prediction include extra packages  
  - [ ] Show extra packages and their impact (e.g. new total limit) in the dashboard card and records

- [ ] Integrate notifications with Telegram  
  - [ ] Add Telegram bot token and chat ID to `data/netmon.conf` (with encrypted storage similar to `NTFY_TOKEN`)  
  - [ ] Implement a `send_telegram(message)` helper alongside ntfy  
  - [ ] Make notification sending pluggable: ntfy, Telegram, or both, based on config  
  - [ ] Document Telegram setup in `README.md` (creating bot, getting chat ID, required config keys)


## License

Use and modify as you like.
