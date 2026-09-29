# Quorum

A congestion-aware campus resource allocator with a FastAPI JSON backend and a static HTML, CSS, and JavaScript frontend.

## Setup

```bash
pip install -r requirements.txt
python backend/seed.py
```

Set `SESSION_SECRET` in `.env` before deployment. The backend contains a clearly marked local-development fallback. `DATABASE_URL` is optional and defaults to the existing root-level SQLite database; set it to another SQLAlchemy URL when moving to PostgreSQL.

All seeded demo accounts use the password `demo1234`. They are also available as one-click options on the login page.

## Run

Start the backend in one terminal:

```bash
python run_backend.py
```

Start the frontend in a second terminal:

```bash
python run_frontend.py
```

Open `http://127.0.0.1:5500`. Keep the `127.0.0.1` hostname so the frontend and API share session cookies correctly.

To start both servers from one terminal instead, run:

```bash
python dev.py
```

### Port already in use

If a launcher reports that port `8000` or `5500` is busy, find the process and stop it before trying again:

```powershell
netstat -ano | findstr :PORT
taskkill /PID <pid> /F
```

## Architecture

- `frontend/`: static pages, the shared visual system in `styles.css`, page behavior in `js/app.js`, and all credentialed API access in `js/api.js`.
- `backend/`: FastAPI application split into `routes/`, `services/`, `models/`, and typed Pydantic `schemas/`. It serves JSON only.
- Database: SQLAlchemy uses `DATABASE_URL`, defaulting to `quorum.db`. The seed script retains hidden demand users for analytics while resetting visible demo users to zero requests.

The frontend origins `http://127.0.0.1:5500` and `http://localhost:5500` are the only origins allowed by CORS. Session requests include credentials and use a SameSite=Lax signed cookie.

## API

Interactive API documentation is available at `http://127.0.0.1:8000/docs`.

- `/api/auth/*`: current user, signup, login, demo login, logout, and demo accounts.
- `/api/resources`: natural-language or structured congestion-aware resource search.
- `/api/resources/{id}`: resource details, unavailable windows, and recent requests.
- `/api/requests`: create a request with conflict alternatives.
- `/api/requests/{id}` and `/api/my-requests`: request details and user history.
- `/api/admin/requests/*`: pending queue plus approve and reject actions.
- `/api/admin/all-requests`: all visible-user requests with status, role, and resource filters.
- `/api/admin/resources/*`: create, update, deactivate, and block resources.
- `/api/admin/dashboard`: request counts, peak hours, congestion, and utilization analytics.

Every endpoint has a tag, summary, typed request schema, and typed response schema in `/docs`.

## Verification

With the API running, verify the database concurrency guarantee:

```bash
python scripts/race_test.py
```

The script logs in through the API, sends 20 simultaneous JSON booking requests for one resource and slot, and must report one success and 19 conflicts.

Natural-language search works without configuration through the built-in rule parser. To use an OpenAI-compatible API, set `LLM_API_KEY`; `LLM_API_URL` and `LLM_MODEL` are optional overrides. API failures fall back to local parsing.
