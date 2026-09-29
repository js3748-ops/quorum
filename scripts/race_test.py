from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta
from http.client import HTTPConnection
from threading import Barrier
from urllib.parse import urlencode, urlparse
import sys


WORKERS = 20


def submit(base_url: str, payload: str, barrier: Barrier) -> tuple[int, str]:
    target = urlparse(base_url)
    connection = HTTPConnection(target.hostname, target.port or 80, timeout=30)
    barrier.wait()
    try:
        connection.request(
            "POST",
            "/requests",
            body=payload,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Cookie": "user_id=1",
            },
        )
        response = connection.getresponse()
        response.read()
        return response.status, response.getheader("Location") or ""
    finally:
        connection.close()


def main() -> None:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    day_offset = 35 + int(datetime.now().timestamp()) % 300
    race_day = date.today() + timedelta(days=day_offset)
    start = datetime.combine(race_day, time(8, 0))
    end = start + timedelta(minutes=30)
    payload = urlencode(
        {
            "resource_id": 6,
            "start": start.strftime("%Y-%m-%dT%H:%M"),
            "end": end.strftime("%Y-%m-%dT%H:%M"),
            "attendees": 4,
            "purpose": "Concurrency race test",
        }
    )
    barrier = Barrier(WORKERS)
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(lambda _: submit(base_url, payload, barrier), range(WORKERS)))

    succeeded = sum(status == 303 and location.startswith("/requests/") for status, location in results)
    rejected = sum(status == 200 for status, _ in results)
    unexpected = WORKERS - succeeded - rejected
    print(f"Slot: {start:%Y-%m-%d %H:%M}")
    print(f"Succeeded: {succeeded}")
    print(f"Rejected: {rejected}")
    if succeeded != 1 or rejected != WORKERS - 1 or unexpected:
        raise SystemExit(
            f"Race test failed: expected 1 success and {WORKERS - 1} conflicts; "
            f"received {unexpected} unexpected responses."
        )


if __name__ == "__main__":
    main()
