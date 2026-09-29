# Quorum

A congestion-aware campus resource allocator built with FastAPI, SQLite, Jinja2, vanilla JavaScript, and hand-written CSS.

This implementation covers Phases 1 through 3.

## Setup

```bash
pip install -r requirements.txt
python scripts/seed.py
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`.

## Demo

1. Use the user switcher in the top bar to change between demo users.
2. Visit Resources to see active campus resources and create a booking request.
3. Visit Admin to add/edit/deactivate resources and add unavailability windows.
4. Try booking an already busy room/time to see a clear conflict reason and alternatives.
5. Book a resource that does not require approval to see immediate approval.
6. Book a resource that requires approval to see a pending request.
7. Switch to Campus Admin, open Approvals, and approve or reject a pending request.
8. Switch back to the requester and open My requests to see the updated status and any rejection note.

Later phases will add natural language search, congestion ranking, dashboards, and the race test.
