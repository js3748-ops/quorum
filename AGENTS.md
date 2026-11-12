# AGENTS.md

Guidance for anyone, human or AI, changing this repo. For the detailed walkthrough, see `docs/quorum-overview.md`. `SPEC.md` is the original brief and is **out of date**. Trust the code.

## Stack

- **Backend:** Python 3.11+, FastAPI 0.115, SQLAlchemy 2.0 (sync, typed `Mapped[...]` models), Pydantic v2 schemas, Starlette signed-cookie sessions (`itsdangerous`), `python-dotenv`. Serves JSON only.
- **Database:** SQLite (`quorum.db` in the repo root, gitignored) through `DATABASE_URL`. There is no Alembic. New columns go in the ad-hoc migration block in `backend/database.py::init_db()`.
- **Frontend:** static HTML, hand-written CSS, vanilla JS, served by `python -m http.server`. No frameworks, chart libraries or build step.
- **LLM:** optional, OpenAI-compatible (`LLM_API_KEY`). The app must work fully without it.
- **Do not add dependencies** beyond `requirements.txt` without explicit approval.

## Run and test

```bash
pip install -r requirements.txt
python backend/seed.py                    # drops and recreates all tables
python dev.py                             # backend :8000 + frontend :5500 (open http://127.0.0.1:5500)

python -m unittest discover -s tests -v   # unit tests (no server)
# integration (needs a running backend on a freshly seeded DB; use a throwaway DATABASE_URL):
python scripts/race_test.py
python scripts/admin_scope_test.py
python scripts/navigation_history_test.py
node scripts/navigation_test.js
```

## Structure

```
backend/main.py            app, middleware, router registration
backend/database.py        engine, get_db, init_db (+ manual migrations)
backend/auth.py            password hashing, login throttle, session validity
backend/models/            all ORM models (one module)
backend/schemas/api.py     all Pydantic request/response models
backend/routes/            thin HTTP layer: auth, resources, bookings, admin, dashboard, sensors, occupancy
backend/routes/dependencies.py   get_current_user / get_admin / get_campus_admin / get_sensor
backend/routes/helpers.py        request_response / resource_response serializers
backend/services/          business logic: booking, analytics, admin_scope, request_events, natural_language, otp, occupancy
frontend/js/api.js         the only fetch() wrapper
frontend/js/app.js         page functions dispatched by <body data-page>
tests/                     unittest, in-memory SQLite, mocked SMTP/LLM
scripts/                   integration scripts against a live API
sensor/                    standalone camera client (YOLO + OpenCV) and simulator; own requirements.txt, NOT part of the backend
```

## Conventions

**Naming and layout**
- Python uses snake_case for functions and columns and PascalCase for models and schemas. Status and enum values are lowercase snake strings (`pending`, `on_hold`, `seminar_hall`, `auto_cancelled_hold`).
- Routes stay thin. Validation and state changes belong in `backend/services/`. Routers use `APIRouter(prefix="/api/...", tags=[...])`.
- Every endpoint declares `response_model`, `summary` and `description`, and takes a typed Pydantic body. Add new schemas to `backend/schemas/api.py`. Serialize requests and resources with `request_response()` and `resource_response()` so timezone handling stays consistent.
- Times: bookings, unavailability, `decided_at`, `confirmed_at` and event `created_at` are naive **IST** (`india_now()`). `requests.created_at` and OTP tables are naive **UTC**. Do not mix them. Bookings use 30-minute slots (`SLOT_MINUTES`).
- Frontend: all API calls go through `window.QuorumAPI`. Escape interpolated values with `escapeHtml()`. Follow the existing design (Instrument Serif / IBM Plex, paper/ink/oxblood palette, 1px rules, mono uppercase status labels, no emojis, gradients, shadows or pill buttons).

**Error handling**
- Services return `str | None` (an error message) or `(obj, error)`. Routes turn errors into `HTTPException`.
- Status codes: 400 for invalid input, 401 when unauthenticated, 403 for the wrong role, 404 when an item is missing **or outside the admin's scope**, 409 for conflicts or state races, 429 for rate limits, 503 when email delivery fails.
- A conflict that needs user action returns a structured `detail`: `{title, reason, alternatives}` for bookings, and `{title, reason, affected_requests}` for hold and unavailability previews.
- Messages are short, plain sentences ending with a period.
- Concurrency-sensitive writes use compare-and-set (`UPDATE … WHERE status = <expected>` and check `rowcount`) and/or the `UNIQUE(resource_id, slot_start)` constraint, catching `IntegrityError` → rollback → 409. Never rely on a read-then-write check alone.

**Auth checks**
- Every endpoint injects exactly one of `get_current_user`, `get_admin` or `get_campus_admin` from `backend/routes/dependencies.py`. Never read `request.session` directly in a route.
- The one machine-facing exception is sensor ingestion (`POST /api/occupancy/readings`), which uses `get_sensor` (the `X-Sensor-Key` header, compared as a SHA-256 hash in constant time). Sensor keys are shown once at create or rotate and never stored in plain text or logged.
- Sensor management (`/api/sensors`) is open to any admin whose scope covers the sensor's resource, not only the Campus Admin.
- Admin lists go through `scope_resource_query(query, admin)` (the query must join `Resource`). Admin single-item actions check `admin_can_access_resource(admin, resource)` and return 404 when it fails.
- User management and resource management are Campus Admin only (`get_campus_admin`).
- Exclude `role == "background"` users from anything user-facing. Admins cannot create bookings or edit their own profile.
- Owners may only see and act on their own requests. Return 404, not 403, for other users' requests.

**Audit logging**
- Write every booking state change with `backend/services/request_events.add_request_event(db, request_id=..., event=..., actor_user_id=..., note=...)`, in the **same transaction** (before the `commit()`) as the change itself.
- Existing event names: `created`, `approved`, `rejected`, `cancelled`, `expired`, `extended`, `auto_cancelled_hold`, `auto_cancelled_unavailability`. Use a new descriptive snake_case name for a new kind of change. Set `actor_user_id` to the acting user, or `None` for system actions.
- When a booking leaves `pending`/`approved`, delete its `BookingSlot` rows in the same transaction.

## Rules for all future work

1. **Never break existing features or tests.** Run the full suite (unit tests and the integration scripts above) after every change, and report the results honestly.
2. **Every state change to a booking must be written to the audit history** (`request_events`) through `add_request_event`, in the same transaction as the change.
3. **All new endpoints follow the existing auth and admin-scope rules.** Use the dependency gates, scope filtering, 404 for out-of-scope items, and Campus-Admin-only management.
4. **Camera frames are never stored or sent anywhere.** Only counts and timestamps leave the sensor. No image or frame data may reach the database, logs, the API, the LLM or any third party. `OccupancyReadingCreate` forbids extra fields to enforce this. Keep it that way.

- Never run git commit or git push. I commit and push myself.

- Never run git commit or git push. I commit and push myself.
