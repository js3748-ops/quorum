# Quorum

A congestion-aware campus resource allocator built with FastAPI, SQLite, Jinja2, vanilla JavaScript, and hand-written CSS.

This implementation covers Phases 1 through 7.

## Setup

```bash
pip install -r requirements.txt
python scripts/seed.py
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`.

Natural-language search works without configuration through the built-in rule parser. To use an OpenAI-compatible API instead, set `LLM_API_KEY`; `LLM_API_URL` and `LLM_MODEL` are optional overrides. API failures automatically fall back to local parsing.

With the app running, verify the database concurrency guarantee:

```bash
python scripts/race_test.py
```

The script sends 20 simultaneous requests for one resource and slot. It must print one success and 19 rejections. Pass a different base URL as the first argument when needed.

## Demo

1. Use the user switcher in the top bar to change between demo users.
2. Search for `Quiet lab with a projector for 4 people tomorrow at 2pm` and review the editable filters.
3. Set the filters to the seeded Wednesday 10:00-11:00 peak and notice that Tech Park North is about 85% loaded.
4. Notice that available rooms in quieter zones rank above Data Studio 212 despite capacity fit.
5. Open Dashboard to compare zone and resource utilization and inspect the peak-hours grid.
6. Visit Admin resources to add/edit/deactivate resources and add unavailability windows.
7. Try booking an already busy room/time to see a clear conflict reason and alternatives.
8. Book a resource that does not require approval to see immediate approval.
9. Book a resource that requires approval to see a pending request.
10. Switch to Campus Admin, open Approvals, and approve or reject a pending request.
11. Switch back to the requester and open My requests to see the updated status and any rejection note.
12. Run `python scripts/race_test.py` and confirm exactly one request succeeds.
