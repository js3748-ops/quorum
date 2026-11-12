# Quorum: codebase overview

Snapshot of branch `feature/quorum-sees` at commit `280eaa4`, written 2026-11-12. This document only describes what exists. It proposes no changes.

Quorum is a booking system for campus resources (labs, classrooms, seminar halls, equipment). It has a FastAPI JSON backend, a static HTML/CSS/vanilla-JS frontend, and a SQLite database accessed through SQLAlchemy 2.x.

> **`SPEC.md` is out of date.** It is the original build brief and differs from the code in several places. It describes Jinja templates, `uvicorn app.main:app`, no authentication, a user switcher, and auto-approval when `requires_approval = false`. Where they disagree, trust the code and this document.

---

## 1. Running locally

Requirements: Python 3.11+ (verified with 3.12.10). Node is only needed for `scripts/navigation_test.js`.

```bash
# from the repo root
pip install -r requirements.txt     # fastapi, uvicorn[standard], sqlalchemy, itsdangerous, python-dotenv
cp .env.example .env                # optional for local demo use; edit values as needed
python backend/seed.py              # WARNING: drops and recreates every table in the target DB
```

Start the servers, either in two terminals:

```bash
python run_backend.py               # uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
python run_frontend.py              # python -m http.server 5500 --bind 127.0.0.1 --directory frontend (also opens a browser)
```

or in one terminal:

```bash
python dev.py                       # starts both; Ctrl+C stops both
```

Equivalent raw commands:

```bash
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
python -m http.server 5500 --bind 127.0.0.1 --directory frontend
```

- Frontend: http://127.0.0.1:5500. Use `127.0.0.1`, not `localhost`. `frontend/js/api.js` hard-codes `http://127.0.0.1:8000`, and the session cookie must be same-site.
- API: http://127.0.0.1:8000. `/` redirects to `/docs` (Swagger).
- The launchers refuse to start if port 8000 or 5500 is busy. Find the process with `netstat -ano | findstr :8000`, then stop it with `taskkill /PID <pid> /F`.
- Demo accounts all use the password `demo1234`. `DEMO_MODE` defaults to `true`, which enables one-click login on the login page and `POST /api/auth/demo-login`. Normal email and password login also needs an emailed OTP, so it requires working SMTP settings.

### Environment variables

| Variable | Default | Used in |
|---|---|---|
| `DATABASE_URL` | `sqlite:///<repo>/quorum.db` | `backend/database.py` |
| `SESSION_SECRET` | `local-development-only-change-me` | `backend/main.py` (session cookie signing) |
| `SESSION_IDLE_MINUTES` / `SESSION_ABSOLUTE_HOURS` | 30 / 12 | `backend/auth.py`, `backend/main.py` |
| `COOKIE_SECURE` | `false` | `backend/main.py` |
| `DEMO_MODE` | `true` | `backend/routes/auth.py` |
| `OTP_SECRET` | falls back to `SESSION_SECRET` | `backend/services/otp.py` |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`, `SMTP_STARTTLS`, `SMTP_USE_SSL` | none | `backend/services/otp.py` |
| `LLM_API_KEY`, `LLM_MODEL` (`openai/gpt-oss-20b`), `LLM_API_URL` (Groq chat-completions) | empty means use the rule parser | `backend/services/natural_language.py` |

---

## 2. Folder structure

```
quorum/
├── backend/
│   ├── main.py                 FastAPI app: routers, SessionMiddleware, CORS (127.0.0.1:5500 / localhost:5500), startup init_db()
│   ├── database.py             engine, SessionLocal, Base, get_db() dependency, init_db() with ad-hoc ALTER TABLE migrations
│   ├── auth.py                 PBKDF2 password hashing, in-memory LoginThrottle, session start/validation (idle + absolute timeout)
│   ├── seed.py                 drop_all + create_all, then seeds zones, resources, demo + background users, ~60 bookings, events
│   ├── models/__init__.py      all SQLAlchemy models (see section 3), plus india_now()
│   ├── schemas/api.py          all Pydantic request and response models (re-exported from backend.schemas)
│   ├── routes/
│   │   ├── dependencies.py     get_current_user, get_admin, get_campus_admin (the auth gates)
│   │   ├── helpers.py          request_response() / resource_response() serializers, approval_message()
│   │   ├── auth.py             /api/auth/*: me, signup(+verify), login(+verify), demo-login, demo-accounts, profile, logout
│   │   ├── resources.py        /api/resources: NL or structured search and ranking; /api/resources/{id} detail
│   │   ├── bookings.py         /api/requests (create, get, cancel), /api/my-requests
│   │   ├── admin.py            /api/admin/*: users, request queue and decisions, extend, all-requests, history (+CSV), resources/holds/unavailability
│   │   ├── dashboard.py        /api/dashboard (user), /api/admin/home, /api/admin/dashboard (analytics)
│   │   ├── sensors.py          /api/sensors: scoped sensor CRUD and key rotation (admins)
│   │   └── occupancy.py        /api/occupancy: sensor reading ingestion (X-Sensor-Key), live view, per-minute history
│   └── services/
│       ├── booking.py          slot maths, conflict detection, create/decide/cancel/extend, alternatives, lazy expiry
│       ├── analytics.py        zone_loads(), ranked_resources() (congestion ranking), current_zone_loads(), weekly dashboard
│       ├── admin_scope.py      ADMIN_SCOPE_TYPES and query/resource scope helpers
│       ├── request_events.py   add_request_event(): the single audit-log writer
│       ├── natural_language.py LLM parser (OpenAI-compatible, 8 s timeout) with rule-based fallback; VagueSearchError
│       ├── otp.py              email OTP challenges: create, consume, SMTP send, rate limits
│       ├── occupancy.py        sensor keys, reading validation and rate limit, smoothing, live view, history, retention
│       └── booking_time.py     INDIA_TIMEZONE, india_now()
├── frontend/
│   ├── *.html                  one page per screen; <body data-page="..."> selects the page function in app.js
│   ├── js/api.js               the only place that calls fetch(); credentials: "include"; 401 redirects to login.html
│   ├── js/app.js               all page logic; `pages` map at the bottom dispatches on data-page
│   └── styles.css              hand-written design system (no frameworks)
├── tests/                      unittest suites (in-memory SQLite, no server needed)
├── scripts/                    integration scripts that hit a running, seeded API (race test, scope test, history test) + a Node nav test
├── dev.py / run_backend.py / run_frontend.py   launchers
├── requirements.txt, .env.example, README.md, SPEC.md (outdated brief)
```

Page to `data-page` mapping: `index` → landing, `login`, `signup`, `profile`, `user-dashboard`, `resources`, `resource`, `book`, `confirmation`, `conflict`, `my-requests`, `admin-home`, `admin-requests` → approvals, `admin-request`, `admin-all-requests` → all-requests, `admin-history`, `admin-users`, `admin-resources`, `dashboard` (admin analytics).

---

## 3. Database models

All models live in `backend/models/__init__.py`. Tables are created with `Base.metadata.create_all`. There is no Alembic: columns added later are applied by hand-written `ALTER TABLE` statements in `init_db()` (`backend/database.py`), which runs on every startup.

**Timestamp convention (watch this):** `requests.created_at` and `auth_challenges.*` hold naive **UTC** (`datetime.utcnow`). `requests.confirmed_at`, `decided_at`, `request_events.created_at`, booking `start`/`end` and unavailability windows hold naive **IST** (`india_now()`, UTC+5:30). `helpers.request_response()` attaches the correct tzinfo when serializing. History date filters shift `created_at` by 5:30 to compensate.

### `zones` (Zone)
`id`, `name`, `building`, `floor`. Seed data has 5 zones. Tech Park North is deliberately overloaded.

### `users` (User)
| field | notes |
|---|---|
| `id` | PK |
| `name` | required |
| `email` | unique, nullable (background users have none) |
| `password_hash`, `password_salt` | PBKDF2-SHA256 hex, 260k iterations |
| `role` | `student` \| `faculty` \| `admin` \| `background` |
| `is_demo` | shows the account in demo login |
| `department` | `CSE`, `ECE`, `EEE`, `Mechanical`, `Civil`, `Biotech`, `Other` |
| `id_number` | unique, stored uppercased |
| `year_of_study` | 1–4, students only |
| `designation` | admins only (for example "Lab Coordinator") |
| `admin_scope` | `all` \| `labs` \| `facilities`; admins only |
| `member_since` | IST |

`background` users are hidden demand used to make analytics realistic. They cannot log in, are filtered out of admin queues and lists, and requests for them return 404.

### `auth_challenges` (AuthChallenge)
`id` (random token PK), `purpose` (`signup`/`login`), `email`, `otp_digest` (HMAC-SHA256 of `challenge_id:otp`; the plaintext OTP is never stored), `context` (JSON; the pending signup fields, including the password hash), `user_id`, `attempts`, `expires_at`, `consumed_at`, `created_at`.

### `resources` (Resource)
| field | notes |
|---|---|
| `id`, `name` | |
| `type` | `lab` \| `classroom` \| `seminar_hall` \| `equipment` |
| `zone_id` | FK to zones |
| `capacity` | int ≥ 1 |
| `equipment` | JSON list of lowercase tags (for example `["projector","linux","gpu"]`) |
| `requires_approval` | stored and editable, but **has no effect on the flow**. Every booking starts `pending` (commit `765574f`). |
| `status` | `active` \| `on_hold` \| `inactive` |
| `hold_reason`, `expected_back` | set while `on_hold` |
| `open_time`, `close_time` | seeds use 08:00–20:00 |

**Resource states:**
- **active**: bookable. Counted in zone capacity for congestion and in utilization open hours.
- **on_hold**: set by `POST /api/admin/resources/{id}/hold` (Campus Admin). This cancels all pending and future approved bookings for the resource. The admin must first receive a 409 preview and then resend with `confirmed_request_ids` matching the affected IDs. Each cancelled booking gets an `auto_cancelled_hold` event and its slots are freed. Not bookable (`validate_request_window` requires `active`). Hidden from search unless `show_on_hold=true`, and then shown with `score = inf`. Listed as a notice on user and admin dashboards. `POST .../lift-hold` returns it to `active`. `PUT /resources/{id}` cannot change the status of an on-hold resource.
- **inactive**: set via `PUT /api/admin/resources/{id}` with `status: "inactive"` (deactivate). Not bookable and excluded from search. Existing bookings are **not** cancelled automatically. The legacy value `maintenance` is migrated to `inactive` on startup.
- Resource state changes are **not** audited. `request_events` only covers requests.

### `unavailability` (Unavailability)
`id`, `resource_id`, `start`, `end`, `reason`. These are closure windows (maintenance, inspection) and block bookings via `find_conflict`. Creating one (`POST /api/admin/resources/{id}/unavailability`) uses the same preview-then-confirm flow as holds. Overlapping pending and approved bookings are cancelled with an `auto_cancelled_unavailability` event.

### `requests` (Request): bookings
| field | notes |
|---|---|
| `id`, `user_id`, `resource_id` | |
| `start`, `end` | naive IST, on 30-minute boundaries, same day, within open hours |
| `attendees` | ≤ resource capacity |
| `purpose` | ≥ 15 characters after strip |
| `status` | `pending` \| `approved` \| `rejected` \| `cancelled` \| `expired` |
| `decided_by`, `decided_at` | the deciding admin, set on approve or reject |
| `rejection_note` | optional admin note on reject |
| `status_reason` | for example "Cancelled by requester", "Resource on hold: …", "Expired before review" |
| `confirmed_at` | IST time the user submitted |
| `created_at` | UTC |

Relationships: `user`, `decider`, `resource`, `slots` (cascade delete), `events` (ordered by time, eager `selectin`).

**Status transitions** (all in `services/booking.py` unless noted):

| from → to | trigger | event written |
|---|---|---|
| (new) → pending | `create_booking_request` | `created` |
| pending → approved | `decide_request` (admin) | `approved` |
| pending → rejected | `decide_request` (admin); slots deleted | `rejected` (note = rejection note) |
| pending / future approved → cancelled | `cancel_request` (owner); slots deleted | `cancelled` |
| pending / future approved → cancelled | resource hold (`routes/admin.py`) | `auto_cancelled_hold` |
| pending / approved overlapping → cancelled | unavailability window (`routes/admin.py`) | `auto_cancelled_unavailability` |
| pending → expired | `expire_pending_requests` once start time passes; slots deleted | `expired` |
| pending / approved, end extended | `extend_booking_request` (admin) | `extended` |

Other rules: admins cannot create bookings (403). A user may hold at most `MAX_PENDING_REQUESTS = 3` pending requests. Bookings must start in the future and fall within 30 days.

### `request_events` (RequestEvent): audit history
`id`, `request_id` (FK), `event` (string: `created`, `approved`, `rejected`, `cancelled`, `expired`, `extended`, `auto_cancelled_hold`, `auto_cancelled_unavailability`), `actor_user_id` (nullable; null for system expiry), `note`, `created_at` (IST).
The only writer is `services/request_events.add_request_event()`, which adds the row to the caller's session. It is committed in the **same transaction** as the state change. Events are returned on every `BookingRequestResponse.events` and drive the timeline UI. Admins search them via `/api/admin/history` (filters: status, date range, resource, requester, deciding admin, free text across purpose, notes and event notes) and export them as CSV via `/api/admin/history.csv`. Both are scope-limited.

### `sensors` (Sensor)
`id`, `resource_id` (FK, indexed), `name`, `api_key_hash` (SHA-256 hex of the full key; the plain key is never stored), `is_active`, `is_simulated`, `last_seen_at` (server receive time of the last accepted reading, IST), `created_at` (IST).
Keys look like `<sensor id>.<random secret>`. The id prefix selects the row, and the hash is then compared with `hmac.compare_digest`. A dummy comparison runs for unknown ids so they take the same time.

### `occupancy_readings` (OccupancyReading)
`id`, `sensor_id` (FK, nullable: set to null when the sensor is deleted so the resource history survives), `resource_id` (FK), `people_count` (CHECK ≥ 0), `recorded_at` (IST; timezone-aware input is converted, naive input is taken as IST). Index `ix_occupancy_readings_resource_recorded` on `(resource_id, recorded_at)`. Rows hold counts and timestamps only.

### `booking_slots` (BookingSlot)
`id`, `request_id`, `resource_id`, `slot_start`, with **`UNIQUE(resource_id, slot_start)`** (`uq_resource_slot`). There is one row per 30-minute slot of every pending or approved request. Rows are deleted on reject, cancel and expire, and added on extend.

---

## 4. Authentication, roles and admin scopes

**Sessions.** Starlette `SessionMiddleware` uses a signed cookie (`itsdangerous`) named `session`, set `HttpOnly` and `SameSite=Lax`, with `Secure` when `COOKIE_SECURE=true`. `auth.start_authenticated_session()` clears the session and stores `user_id`, a fresh random `session_id`, `authenticated_at` and `last_seen`. `auth.authenticated_session_is_valid()` enforces a 30-minute idle timeout and a 12-hour absolute lifetime, and refreshes `last_seen` on each request.

**Login flow** (`routes/auth.py`):
1. `POST /api/auth/login` throttles per email+IP (5 failures in 15 minutes) and per IP (20). It always runs PBKDF2, even for unknown emails, to prevent timing leaks. It then creates an OTP challenge and emails a 6-digit code (202 + `challenge_id`).
2. `POST /api/auth/login/verify` consumes the code (single use, 10-minute TTL, maximum 5 attempts) and starts the session.
3. Signup works the same way (`/signup` → `/signup/verify`). The account is created only after the OTP is verified. Self-signup allows only `student` or `faculty`.
4. OTP sending is limited to one per 60 s and 5 per hour per email and purpose.
5. `POST /api/auth/demo-login` skips password and OTP for `is_demo` users when `DEMO_MODE` is on.

**Dependencies** (`routes/dependencies.py`). These are the only auth gates. Inject one into every endpoint:
- `get_current_user` returns 401 if the session is invalid, the user is missing, or the user has the `background` role.
- `get_admin` adds a check for `role == "admin"`, otherwise 403 "Admin access required."
- `get_campus_admin` adds a check for `admin_scope == "all"`, otherwise 403 "Campus Admin access required."

**Admin scopes** (`services/admin_scope.py`):

| scope | label | resource types |
|---|---|---|
| `all` | Campus Admin | lab, classroom, seminar_hall, equipment |
| `labs` | Lab Coordinator | lab |
| `facilities` | Facilities Officer | classroom, seminar_hall, equipment |

- Lists use `scope_resource_query(query, admin)`, which adds `Resource.type IN (...)` unless the scope is `all`. The query must already join `Resource`.
- Single-item actions use `admin_can_access_resource(admin, resource)`. Out-of-scope items return **404 "Request not found."**, not 403, so their existence is not leaked.
- Campus Admin only (`get_campus_admin`): user management (`/api/admin/users`) and all resource management (`/api/admin/resources*`: create, update, hold, lift-hold, unavailability).
- Any admin (`get_admin` + scope filter): pending queue, request detail, approve, reject, extend, all-requests, history, CSV, request-resources, admin home, analytics dashboard. The analytics dashboard (`/api/admin/dashboard`) is **not** scope-filtered.
- Admins cannot edit their own profile or role (403).
- Owners see their own requests. `GET /api/requests/{id}` also allows any admin, with **no scope check** on that route.

Seeded demo users (password `demo1234`): students `asha@`, `kabir@`, `nila@`; faculty `ananya@`, `rohan@`; admins `admin@` (all), `lab.coordinator@` (labs), `facilities@` (facilities). All are on the `@quorum.local` domain.

---

## 4a. Occupancy sensors

**Admin endpoints** (`routes/sensors.py`, gate `get_admin` + `admin_can_access_resource`; out-of-scope returns 404):
- `POST /api/sensors` `{resource_id, name, is_simulated?}` returns 201 `{sensor, api_key, message}`. The key is shown once, with `Cache-Control: no-store`.
- `GET /api/sensors` lists scoped sensors with `resource_name`, `status` (`online` if a reading arrived in the last 60 s, `offline`, or `inactive`) and `last_seen_at`.
- `PATCH /api/sensors/{id}` `{name?, is_active?}` (at least one is required).
- `POST /api/sensors/{id}/rotate-key` issues a new key, shown once. The old key stops working immediately.
- `DELETE /api/sensors/{id}` revokes the key. Readings are kept with `sensor_id = null`.

**Sensor endpoint:** `POST /api/occupancy/readings` with header `X-Sensor-Key`, body `{people_count, recorded_at?}`. Unknown fields are rejected (422), so no image data can be posted.
- 401: missing or wrong key. 403: sensor inactive. 422: count not an integer in 0–1000. 400: `recorded_at` more than 2 minutes in the future.
- 429 + `Retry-After`: more than one reading per sensor within 2 seconds. This is enforced atomically by a compare-and-set on `sensors.last_seen_at`, which is also how `last_seen_at` gets updated.

**Read endpoints** (any signed-in user via `get_current_user`):
- `GET /api/occupancy/live` returns, for every resource: `current_booking` (the approved request covering now: `request_id`, `start`, `end`, `expected_attendance`; no requester details), `people_count` (median of active-sensor readings with `recorded_at` in the last 60 s, rounded half up; null if there are none), `capacity`, `sensor_status` (`online` / `offline` / `unsensored` = no active sensor), `last_reading_at`, and `status` (always `"unknown"` for now; computed in a later phase).
- `GET /api/occupancy/{resource_id}/history?from=&to=` returns per-minute buckets (`average`, `median`, `min`, `max`, `readings`). It defaults to the last hour, allows at most 7 days, and returns 400 for an inverted range and 404 for an unknown resource.

**Retention:** `services/occupancy.purge_old_readings()` deletes readings older than 30 days. With no scheduler in the codebase, it runs once in the FastAPI startup hook (`backend/main.py`).

Occupancy timestamps in API responses carry the IST offset (`+05:30`).

## 5. Congestion-aware ranking

Entry point: `GET /api/resources` (`routes/resources.py::search_resources`) → `services/analytics.py::ranked_resources()`.

**Inputs:** `resource_type`, `attendees`, `equipment` list, `start`, `end`, `show_on_hold`. These come either from query parameters or from the natural-language parser `parse_natural_language(q)`. The parser calls an LLM when `LLM_API_KEY` is set and falls back to rules otherwise. It returns only `{type, attendees, equipment, date, start_time, end_time}` and never sees the database. A vague query returns 400 with a clarification. Without explicit times, the search window defaults to Wednesday 10:00–11:00 of the current week.

**Zone load:** `zone_loads(db, start, end)`

```
load[zone] = SUM(attendees of pending+approved requests in that zone overlapping [start, end))
           / SUM(capacity of resources in that zone with status == "active")
```
This includes background-user demand. Zones with no active capacity are omitted (treated as 0).

**Filtering, in `ranked_resources`:**
1. Status is `active` (or `active`/`on_hold` if `show_on_hold`), and `capacity >= attendees`, and the type matches if one was given.
2. The resource's equipment (lowercased) is a superset of the requested equipment.
3. `find_conflict()` runs for active resources. Any conflict other than "Booked …" (outside hours, inactive, unavailability window) drops the resource. A "Booked …" conflict keeps the resource but marks it unavailable with `score = inf` and label "Already booked".

**Score (lower is better):**
```python
wasted_capacity    = (capacity - attendees) / capacity
congestion_penalty = load * 35 + max(0, load - 0.6) * 180    # steep above 60 %
score              = wasted_capacity * 40 + congestion_penalty
# on_hold or already booked → score = inf
```
Results are sorted by `(score, capacity)`. Reason strings: `"<Zone> at NN%, ranked lower"` (load > 0.6), `"Quieter zone"` (≤ 0.3), otherwise `"Moderate zone load"`, or `"On hold: …"` / `"Already booked for this time"`. Each result includes `zone_load`, `load_percent`, and `bar_width` (capped at 100).

Related: `current_zone_loads()` computes the zone loads for the next 30 minutes on the user dashboard. The admin request detail page shows the zone load for that request's window. `current_week_dashboard()` provides utilization (booked hours / open hours over 7 days), a peak-hours grid (08:00–20:00 × 7 days, booked requests / active resource count) and status counts.

Note: search uses `datetime.now()` (machine local time) for defaults, while booking validation uses `india_now()`.

---

## 6. Conflict prevention and the race test

There are three layers, all in `services/booking.py`.

1. **Validation:** `validate_request_window()` checks that end > start, both are on :00/:30 boundaries, both are within open hours, and the resource is `active`. `validate_booking_horizon()` (called from the route) rejects past starts and anything more than 30 days ahead.
2. **Pre-check:** `find_conflict()` checks for an overlapping `Unavailability` row ("Closed for maintenance 13:00-16:00.") and any existing `BookingSlot` for the resource whose `slot_start` is one of the requested slots ("Booked 10:00-11:30 by another request.").
3. **Database guarantee:** `create_booking_request()` inserts the `Request`, its `created` event and one `BookingSlot` per 30-minute slot in a single transaction. If two requests pass the pre-check concurrently, the `UNIQUE(resource_id, slot_start)` constraint makes one commit fail with `IntegrityError`. That request is rolled back (the request and event rows disappear with it) and reported as "This slot was just booked by another request."

On any conflict the route returns **409** with `detail = {title: "Conflict" | "Outside open hours", reason, alternatives[≤3]}`. `suggest_alternatives()` returns the nearest free times for the same resource, then similar resources (same type, enough capacity, an equipment superset) at the requested time or their nearest free time.

The same pattern protects other races:
- `decide_request` uses `UPDATE … WHERE status='pending'` and checks `rowcount`. A second admin gets 409 "Already approved by X at …".
- `cancel_request` and `extend_booking_request` use compare-and-set updates. Extension inserts new slots under the same unique constraint.
- `reserve_pending_capacity` runs a no-op `UPDATE users SET id=id` to take a write lock before counting pending requests, which enforces the 3-pending limit.

**Race test:** `scripts/race_test.py [base_url]` (default `http://127.0.0.1:8000`) needs a running, seeded API.
1. Logs in as demo student `asha@quorum.local` via `/api/auth/demo-login` and captures the session cookie.
2. Builds one payload: resource **id 6** (Quiet Room L1), 08:00–08:30 on a day 20–27 days ahead (varied by timestamp to avoid reuse), 4 attendees.
3. Opens 20 threads that wait on a `threading.Barrier(20)` and then simultaneously `POST /api/requests`.
4. Asserts exactly **1 × 201** and **19 × 409**. Anything else exits non-zero.
5. Cleans up by cancelling the successful request via `/api/requests/{id}/cancel`, so asha's pending count stays under 3.

---

## 7. Test suite

**Unit tests:** stdlib `unittest`, with no pytest dependency and no server. They use in-memory SQLite and mock SMTP and the LLM. Run from the repo root:

```bash
python -m unittest discover -s tests -v
```

| file | covers |
|---|---|
| `tests/test_auth_otp_flow.py` | login and signup need and consume an OTP before any session or user exists |
| `tests/test_auth_security.py` | login throttle lockout and reset, session rotation, expiry |
| `tests/test_natural_language.py` | LLM-first parsing, clarification for vague queries, rule fallback edge cases |
| `tests/test_otp.py` | hashed single-use codes, attempt limit, expiry, resend throttle |
| `tests/test_occupancy.py` | sensor key auth (valid, wrong, malformed, inactive, rotated, deleted), reading validation, 2 s rate limit, admin scope, median smoothing, live and offline status, history buckets, 30-day purge |

**Integration scripts:** these need a running backend on a **freshly seeded** database. They create real bookings, so point them at a throwaway DB, for example `DATABASE_URL=sqlite:///path/to/tmp.db`.

```bash
python backend/seed.py
python run_backend.py                      # in another terminal
python scripts/race_test.py                # 20 concurrent bookings → 1 success, 19 conflicts
python scripts/admin_scope_test.py         # scope isolation, campus-only endpoints, self-edit 403, concurrent approve → [200, 409]
python scripts/navigation_history_test.py  # admin booking 403, hold preview/cancel + audit events, scoped history + CSV, slot release
node scripts/navigation_test.js            # offline: landing redirect and header home link per role (runs app.js in a vm sandbox)
```

`admin_scope_test.py` and `navigation_history_test.py` read `QUORUM_API_URL` (default `http://127.0.0.1:8000`).

**Current result (2026-11-12, Python 3.12.10, Node 26.13.1):**
- Unit tests: **15 / 15 passed** (`Ran 15 tests … OK`). Only `datetime.utcnow()` deprecation warnings were printed.
- `race_test.py`: **passed**, Succeeded 1, Rejected 19.
- `admin_scope_test.py`: **passed**.
- `navigation_history_test.py`: **passed**.
- `navigation_test.js`: **passed**.

The integration scripts ran against a seeded scratch database outside the repo, so `quorum.db` was not touched.

---

## 8. Background jobs and schedulers

**There are none.** (Occupancy retention runs once per server start; see section 4a.) The repo has no scheduler, cron, worker thread, `BackgroundTasks` or asyncio task. The only startup hook is `init_db()`. Time-based behaviour happens lazily, inside normal requests:

- `expire_pending_requests(db)` runs at the top of almost every booking, resource, admin and dashboard endpoint. It flips pending requests whose `start <= india_now()` to `expired`, deletes their slots, writes an `expired` event (actor null) and commits. A request only expires once someone calls the API.
- Old OTP challenges (more than 1 day old) are deleted inside `create_otp_challenge`.
- `LoginThrottle` state is in-process memory. It resets on restart and is not shared across workers.

Occupancy sensors (section 4a) post people counts over HTTP. The backend accepts only counts and timestamps, never images.
