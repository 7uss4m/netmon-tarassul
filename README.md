# Netmon Tarassul

A **Syrian Telecom Self Portal** monitor: fetches your internet package usage from the telecom API, stores history, and notifies you via [ntfy](https://ntfy.sh) when usage hits 25%, 50%, 75%, 90%, or 100%.

## Features

- **Automatic fetches** — Runs twice daily at configurable hours (default 8:00 and 20:00)
- **Usage dashboard** — View current usage %, monthly volume, limit, and projected exceed day
- **History** — Per-month fetch history
- **ntfy alerts** — Push notifications at usage thresholds (one notification per threshold per month)
- **Protected web UI** — JWT-based login; change password in Settings
- **SQLite storage** — All data and settings in a single database file

> **Note:** Run this on a **local server** (e.g. at home). The Syrian Telecom API only accepts requests from Syrian IPs, so the app must run on a machine inside Syria (same network as your connection). Do not run it on a cloud/VPS abroad — fetches will fail.

## Prerequisites

- **Python 3.12+** (or use Docker)
- Syrian Telecom Self Portal credentials (username/password)

## Quick start with Docker

```bash
# Optional: set a strong JWT secret
export JWT_SECRET=your-secret-here

docker compose up -d
```

Open **http://localhost:5000**. Default login: **admin** / **admin** — change the password in Settings.

Data is stored in `./portal_data/data.db`.

## Run locally (without Docker)

1. **Create a virtual environment and install dependencies** (from repo root)

   ```bash
   python -m venv .venv
   .venv\Scripts\activate   # Windows
   # source .venv/bin/activate   # Linux/macOS
   pip install -r requirements.txt
   ```

2. **Optional: set environment variables**

   - `JWT_SECRET` — Secret for JWT cookies (default: `change-me-in-production`)
   - `PORT` — Server port (default: `5000`)
   - `PORTAL_DB` — Path to SQLite database (default: `src/data.db` when run from `src/`)

3. **Start the app** (run from the `src` folder)

   ```bash
   cd src
   python app.py
   ```

   Then open **http://localhost:5000**.

## Configuration (Settings)

Configure in the web UI under **Settings**, or via `POST /api/settings` (JSON body). Stored in SQLite.

| Setting | Description |
|--------|-------------|
| `telecom_base_url` | Syrian Telecom Self Portal API URL |
| `telecom_fid` | Portal F_ID (default `3`) |
| `telecom_username` | Your telecom username |
| `telecom_password` | Your telecom password |
| `telecom_lang` | Language code (e.g. `1`) |
| `fetch_hour_1` | First daily fetch hour (0–23) |
| `fetch_hour_2` | Second daily fetch hour (0–23) |
| `ntfy_url` | ntfy topic URL (e.g. `https://ntfy.sh/YourTopic`) |

After saving settings, the scheduler is updated automatically.

## API (all require JWT cookie)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/latest` | Latest fetch result |
| GET | `/api/history?month_begin=YYYY-MM-DD` | History for a billing month |
| POST | `/api/fetch` | Trigger a fetch now |
| GET/POST | `/api/settings` | Read or update settings |
| POST | `/api/settings/password` | Change dashboard password (JSON: `{"password": "new"}`) |

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
| `db.py` | SQLite schema, settings, fetches, notifications, password |
| `fetcher.py` | Telecom API fetch, usage computation, ntfy notifications |
| `scheduler.py` | APScheduler: twice-daily fetch jobs |
| `templates/` | Login, dashboard, settings HTML |


## License

Use and modify as you like.
