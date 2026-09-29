# Quorum

A congestion-aware campus resource allocator built with FastAPI, SQLite, Jinja2, vanilla JavaScript, and hand-written CSS.

This implementation covers Phases 1 through 3, Phase 5, and Phase 6. Phase 4 is intentionally not included yet.

## Setup

```bash
pip install -r requirements.txt
python scripts/seed.py
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`.

## Demo

1. Use the user switcher in the top bar to change between demo users.
2. Visit Resources. The default seeded search uses Wednesday 10:00-11:00, when Tech Park North is about 85% loaded.
3. Notice that available rooms in quieter zones rank above Data Studio 212 despite capacity fit.
4. Open Dashboard to compare zone and resource utilization and inspect the peak-hours grid.
5. Visit Admin resources to add/edit/deactivate resources and add unavailability windows.
6. Try booking an already busy room/time to see a clear conflict reason and alternatives.
7. Book a resource that does not require approval to see immediate approval.
8. Book a resource that requires approval to see a pending request.
9. Switch to Campus Admin, open Approvals, and approve or reject a pending request.
10. Switch back to the requester and open My requests to see the updated status and any rejection note.

Later phases will add natural language search and the race test.
