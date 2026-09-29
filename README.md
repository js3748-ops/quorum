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

Set `SESSION_SECRET` in `.env` before deployment. A clearly marked development-only fallback is used when it is absent.

Seeded demo accounts use the password `demo1234` and are listed on the login page. Admin accounts are seed-only; sign-up supports student and faculty accounts.

Natural-language search works without configuration through the built-in rule parser. To use an OpenAI-compatible API instead, set `LLM_API_KEY`; `LLM_API_URL` and `LLM_MODEL` are optional overrides. API failures automatically fall back to local parsing.

With the app running, verify the database concurrency guarantee:

```bash
python scripts/race_test.py
```

The script sends 20 simultaneous requests for one resource and slot. It must print one success and 19 rejections. Pass a different base URL as the first argument when needed.

## Demo

1. Log in with a demo account or create a student or faculty account.
2. Search for `Quiet lab with a projector for 4 people tomorrow at 2pm` and review the editable filters.
3. Set the filters to the seeded Wednesday 10:00-11:00 peak and notice that Tech Park North is about 85% loaded.
4. Notice that available rooms in quieter zones rank above Data Studio 212 despite capacity fit.
5. Open Dashboard to compare zone and resource utilization and inspect the peak-hours grid.
6. Visit Admin resources to add/edit/deactivate resources and add unavailability windows.
7. Try booking an already busy room/time to see a clear conflict reason and alternatives.
8. As a student, book any resource to see a pending request awaiting admin review.
9. As faculty, book an ordinary resource for immediate approval or an approval-required resource for review.
10. Log in as Campus Admin, open Approvals, and approve or reject a pending request.
11. Use All requests to filter visible-user requests by status, role, and resource.
12. Log back in as the requester and open My requests to see the updated status and any rejection note.
13. Run `python scripts/race_test.py` and confirm exactly one request succeeds.
