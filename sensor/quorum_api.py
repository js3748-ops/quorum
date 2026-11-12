"""Minimal client for Quorum's sensor endpoint, shared by the camera client and the simulator.

Standard library only. It sends exactly {"people_count": n} with the X-Sensor-Key header to
POST <QUORUM_URL>/api/occupancy/readings. Nothing else is ever sent: no images, no frames.
"""

import json
import math
import socket
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SERVER_MIN_GAP_SECONDS = 2.0  # Quorum accepts one reading per sensor every 2 seconds.
SAFE_GAP_SECONDS = 2.2  # Small margin so clock jitter never trips the server's limit.
MAX_BACKOFF_SECONDS = 60.0
AUTH_RETRY_SECONDS = 30.0  # A rejected or switched-off key will not fix itself quickly.
REQUEST_TIMEOUT_SECONDS = 5.0


@dataclass
class PostResult:
    ok: bool
    status: int | None  # None means the server could not be reached.
    message: str
    retry_after: float | None = None
    reading_id: int | None = None


def mask_key(key: str) -> str:
    """Show enough of a key to identify it in logs without revealing the secret."""
    key = key or ""
    sensor_id, _, secret = key.partition(".")
    return f"{sensor_id}.{secret[:4]}..." if secret else "(not set)"


def _error_detail(raw: bytes) -> str:
    try:
        detail = json.loads(raw or b"null").get("detail")
    except (ValueError, AttributeError):
        return raw.decode("utf-8", "replace")[:200] or "no details"
    if isinstance(detail, list):  # FastAPI validation errors (422)
        parts = []
        for item in detail:
            field = ".".join(str(part) for part in item.get("loc", []) if part != "body")
            parts.append(f"{field}: {item.get('msg', 'invalid')}" if field else item.get("msg", "invalid"))
        return "; ".join(parts) or "invalid reading"
    return str(detail or "no details")


def post_reading(base_url: str, sensor_key: str, people_count: int) -> PostResult:
    url = base_url.rstrip("/") + "/api/occupancy/readings"
    body = json.dumps({"people_count": int(people_count)}).encode("utf-8")
    request = Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Sensor-Key": sensor_key,
            "User-Agent": "quorum-sensor/1.0",
        },
    )
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            data = json.loads(response.read() or b"null") or {}
            return PostResult(True, response.status, "accepted", reading_id=data.get("id"))
    except HTTPError as error:  # must come before URLError (it is a subclass)
        retry_header = error.headers.get("Retry-After") if error.headers else None
        try:
            retry_after = float(retry_header) if retry_header else None
        except ValueError:
            retry_after = None
        return PostResult(False, error.code, _error_detail(error.read()), retry_after=retry_after)
    except (URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as error:
        reason = getattr(error, "reason", error)
        return PostResult(False, None, str(reason) or error.__class__.__name__)
    except Exception as error:  # never let an odd network failure crash a sensor loop
        return PostResult(False, None, f"{error.__class__.__name__}: {error}")


class ReadingSender:
    """Schedules posts for one sensor: fixed interval, rate-limit safe, backoff when unreachable."""

    def __init__(self, base_url: str, sensor_key: str, interval: float, label: str = "sensor", log=print):
        self.base_url = base_url
        self.sensor_key = sensor_key
        self.interval = max(float(interval), SAFE_GAP_SECONDS)
        self.label = label
        self.log = log
        self.next_at = 0.0
        self.backoff = 0.0
        self.sent = 0

    def due(self, now: float | None = None) -> bool:
        return (time.monotonic() if now is None else now) >= self.next_at

    def seconds_until_due(self) -> float:
        return max(0.0, self.next_at - time.monotonic())

    def delay_start(self, seconds: float) -> None:
        self.next_at = time.monotonic() + seconds

    def send(self, people_count: int) -> PostResult:
        result = post_reading(self.base_url, self.sensor_key, people_count)
        now = time.monotonic()
        stamp = time.strftime("%H:%M:%S")
        prefix = f"[{stamp}] [{self.label}]"

        if result.ok:
            self.backoff = 0.0
            self.sent += 1
            self.next_at = now + self.interval
            self.log(f"{prefix} sent people_count={people_count} (reading #{result.reading_id})")
        elif result.status is None or result.status >= 500:
            self.backoff = min(MAX_BACKOFF_SECONDS, self.backoff * 2 if self.backoff else 2.0)
            self.next_at = now + self.backoff
            what = "server unreachable" if result.status is None else f"server error {result.status}"
            self.log(f"{prefix} {what} ({result.message}); retrying in {self.backoff:.0f}s")
        elif result.status == 429:
            wait = max(result.retry_after or SERVER_MIN_GAP_SECONDS, SAFE_GAP_SECONDS)
            self.next_at = now + wait
            self.log(f"{prefix} 429 rate limited: {result.message} Waiting {wait:.1f}s.")
        elif result.status == 401:
            self.next_at = now + AUTH_RETRY_SECONDS
            self.log(
                f"{prefix} 401 sensor key rejected (key {mask_key(self.sensor_key)}). "
                f"Check SENSOR_KEY, or rotate the key in Quorum. Retrying in {AUTH_RETRY_SECONDS:.0f}s."
            )
        elif result.status == 403:
            self.next_at = now + AUTH_RETRY_SECONDS
            self.log(
                f"{prefix} 403 {result.message} Ask an admin to activate the sensor. "
                f"Retrying in {AUTH_RETRY_SECONDS:.0f}s."
            )
        elif result.status == 422:
            self.next_at = now + self.interval
            self.log(f"{prefix} 422 reading rejected as invalid: {result.message}")
        else:
            self.next_at = now + self.interval
            self.log(f"{prefix} {result.status} reading rejected: {result.message}")
        return result


def round_half_up(value: float) -> int:
    return int(math.floor(value + 0.5))
