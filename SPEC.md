# Build: Quorum — a congestion-aware resource allocator

You are building a working web app in about 3 hours. Work in the phases below, in order. At the end of each phase, run the app, confirm it works, and stop to summarise what you built before continuing. Keep the code simple and readable; avoid adding libraries unless they are listed here.

## Concept

A booking system for campus resources (labs, classrooms, seminar halls, equipment) that treats allocation as a load-balancing problem. When a user searches, rooms in less crowded zones of campus rank higher, so foot traffic spreads out instead of piling into one building. Users can search in plain English, and double bookings are prevented by the database itself.

## Stack

- Backend: FastAPI, Python 3.11+
- Database: SQLite via SQLAlchemy (sync is fine)
- Frontend: Jinja2 templates served by FastAPI, vanilla JavaScript, hand-written CSS. No CSS frameworks, no React, no component libraries.
- LLM: any OpenAI-compatible API, key read from an `LLM_API_KEY` environment variable. The app must work fully without a key (see Phase 4).
- One command to run: `uvicorn app.main:app --reload`
- Include a `requirements.txt` and a short README with setup steps.

## Roles

No real authentication. Seed a handful of demo users (some students/faculty, one admin). A small user switcher in the top bar lets the presenter change who they are acting as. Admin-only pages check the current user's role.

## Data model

- `zones`: id, name (e.g. "Tech Park North"), building, floor
- `resources`: id, name, type (lab, classroom, seminar_hall, equipment), zone_id, capacity, equipment (JSON list, e.g. ["projector", "linux", "gpu"]), requires_approval (bool), status (active, maintenance), open_time, close_time
- `unavailability`: id, resource_id, start, end, reason (maintenance, holidays)
- `requests`: id, user_id, resource_id, start, end, attendees, purpose, status (pending, approved, rejected, cancelled), decided_by, decided_at, created_at
- `booking_slots`: request_id, resource_id, slot_start — one row per 30-minute slot a request covers. Unique index on (resource_id, slot_start). Slots are inserted for pending and approved requests and deleted when a request is rejected or cancelled.

All times are in 30-minute slots. Validate that bookings fall on slot boundaries and within the resource's open hours.

## Phases

### Phase 1 — Resources and availability
- Admin page to register, edit and deactivate resources, and to add unavailability windows.
- Seed script: 5 zones, about 25 resources with varied capacity and equipment, 8 demo users, and about 60 bookings spread across the current week with realistic peaks (mornings busy, one zone clearly overloaded).

### Phase 2 — Requests, allocation and conflicts
- Users create a request for a resource and time range.
- Resources with `requires_approval = false` are approved immediately; others go to pending.
- Conflict detection: before insert, check overlaps against booking_slots and unavailability, and return a clear reason ("Booked 10:00–11:30 by another request", "Closed for maintenance"). The unique index is the final guarantee: wrap the slot inserts in a transaction, and if an IntegrityError occurs, roll back and return a conflict.
- When there is a conflict, suggest up to 3 alternatives: the same resource at the nearest free times, and similar resources (same type, capacity and equipment) at the requested time.

### Phase 3 — Approval workflow
- Admin queue of pending requests, sorted oldest first, with approve and reject buttons and an optional rejection note.
- Rejecting frees the slots immediately.
- Users see their requests with status on a "My requests" page.

### Phase 4 — Natural language search
- A command bar at the top of the search page: "Quiet lab with a projector for 4 people tomorrow at 2pm."
- The LLM returns only structured JSON: { type, attendees, equipment, date, start_time, end_time }. Do not send the database to the LLM, and never let it choose a resource.
- Always show the parsed values as editable filter fields below the bar, so the user can see and correct the interpretation.
- Fallback: if there is no API key or the call fails, parse with simple rules (dates like "today", "tomorrow", weekday names; times like "2pm", "14:00"; numbers followed by "people"; known equipment keywords). The UI should not visibly break either way.

### Phase 5 — Congestion-aware ranking
- Zone load for a time window = (sum of attendees in approved/pending requests in that zone overlapping the window) / (total capacity of active resources in the zone).
- Filter resources by hard constraints first: type, capacity, equipment, open hours, no conflicts.
- Score the remaining ones: prefer the smallest room that fits (penalise wasted capacity), then apply a congestion penalty that grows with zone load and becomes heavy above 60%.
- Show results as a table: resource, zone, capacity, equipment, zone load as a thin inline bar with a percentage, and a short plain reason ("Quieter zone", "Tech Park North at 72%, ranked lower"). One Book button per row.

### Phase 6 — Utilization dashboard
- Utilization per resource and per zone for the current week (booked hours / open hours).
- A peak-hours grid (days × time slots) shaded by load, drawn with plain CSS or SVG.
- Counts of pending, approved and rejected requests, and the most and least used resources.
- Keep charts hand-built with SVG; no chart libraries.

### Phase 7 — Concurrency proof
- A script `scripts/race_test.py` that fires 20 simultaneous booking requests for the same resource and slot at the running API and prints how many succeeded (must be exactly 1) and how many were rejected.

## Design

Minimal, editorial, calm. It should look like a well-typeset timetable, not a SaaS template.

- Fonts from Google Fonts: "Instrument Serif" for page titles and large numbers, "IBM Plex Sans" for body text, "IBM Plex Mono" for times, room codes and percentages. Provide sensible fallbacks.
- Palette: warm paper background (#F5F2EC), near-black ink text (#1C1B19), muted grey rules (#D9D4CA), and a single accent (deep oxblood, #7A2E2A) used sparingly for primary actions and overload warnings. A muted olive (#5E6B45) for "quiet zone" indicators.
- Layout: generous whitespace, a narrow top bar, thin 1px rules instead of cards with shadows, left-aligned text, tabular numbers in tables.
- The command bar is the focal point: large, serif placeholder text, a thin underline instead of a boxed input.
- Status appears as small uppercase mono labels (PENDING, APPROVED), not coloured pills.
- Do not use: emojis, gradients, glassmorphism, drop shadows, sparkle or "AI" icons, rounded pill buttons, stock illustrations, or marketing copy such as "Powered by AI" or "Revolutionise". Interface text should be short and plain.
- Must be usable on a laptop screen at 1280px wide; mobile is a bonus.

## Done means

- Every phase runs without errors from a fresh clone after `pip install -r requirements.txt`, running the seed script and starting uvicorn.
- The race test prints exactly one success.
- The README lists the run commands and a 2-minute demo script: natural language search, congestion ranking, a conflict with alternatives, an approval, the dashboard, and the race test.