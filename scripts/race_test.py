from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta
from http.client import HTTPConnection
from http.cookies import SimpleCookie
import json
import sys
from threading import Barrier
from urllib.parse import urlparse


WORKERS = 20


def login(base_url: str) -> str:
    target = urlparse(base_url)
    connection = HTTPConnection(target.hostname, target.port or 80, timeout=30)
    try:
        connection.request(
            "POST",
            "/api/auth/demo-login",
            body=json.dumps({"email": "asha@quorum.local"}),
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        response.read()
        if response.status != 200:
            raise SystemExit(f"Demo login failed with status {response.status}. Run the seed script first.")
        cookie = SimpleCookie()
        cookie.load(response.getheader("Set-Cookie") or "")
        if "session" not in cookie:
            raise SystemExit("Login did not return a session cookie.")
        return f"session={cookie['session'].value}"
    finally:
        connection.close()


def submit(base_url: str, payload: str, barrier: Barrier, session_cookie: str) -> tuple[int, int | None]:
    target = urlparse(base_url)
    connection = HTTPConnection(target.hostname, target.port or 80, timeout=30)
    barrier.wait()
    try:
        connection.request(
            "POST",
            "/api/requests",
            body=payload,
            headers={
                "Content-Type": "application/json",
                "Cookie": session_cookie,
            },
        )
        response = connection.getresponse()
        body = response.read()
        data = json.loads(body or b"null")
        return response.status, data.get("id") if isinstance(data, dict) else None
    finally:
        connection.close()


def main() -> None:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    day_offset = 20 + int(datetime.now().timestamp()) % 8
    race_day = date.today() + timedelta(days=day_offset)
    start = datetime.combine(race_day, time(8, 0))
    end = start + timedelta(minutes=30)
    payload = json.dumps(
        {
            "resource_id": 6,
            "start": start.strftime("%Y-%m-%dT%H:%M"),
            "end": end.strftime("%Y-%m-%dT%H:%M"),
            "attendees": 4,
            "purpose": "Concurrency race test",
            "confirmed": True,
        }
    )
    session_cookie = login(base_url)
    barrier = Barrier(WORKERS)
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(
            pool.map(
                lambda _: submit(base_url, payload, barrier, session_cookie),
                range(WORKERS),
            )
        )

    statuses = [status for status, _ in results]
    succeeded = sum(status == 201 for status in statuses)
    rejected = sum(status == 409 for status in statuses)
    unexpected = WORKERS - succeeded - rejected
    print(f"Slot: {start:%Y-%m-%d %H:%M}")
    print(f"Succeeded: {succeeded}")
    print(f"Rejected: {rejected}")
    if succeeded != 1 or rejected != WORKERS - 1 or unexpected:
        raise SystemExit(
            f"Race test failed: expected 1 success and {WORKERS - 1} conflicts; "
            f"received {unexpected} unexpected responses."
        )
    successful_id = next(request_id for status, request_id in results if status == 201)
    connection = HTTPConnection(urlparse(base_url).hostname, urlparse(base_url).port or 80, timeout=30)
    try:
        connection.request(
            "POST",
            f"/api/requests/{successful_id}/cancel",
            body="{}",
            headers={"Content-Type": "application/json", "Cookie": session_cookie},
        )
        response = connection.getresponse()
        response.read()
        if response.status != 200:
            raise SystemExit(f"Race-test cleanup failed with status {response.status}.")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
