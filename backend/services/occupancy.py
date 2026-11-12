"""Occupancy sensors: key management, reading ingestion, live view, history, retention.

Privacy rule: sensors send only a people count and a timestamp. Nothing in this
module accepts, stores or forwards image or frame data.
"""

import hashlib
import hmac
import math
import secrets
import statistics
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session, joinedload

from backend.models import OccupancyReading, Request, Resource, Sensor
from backend.services.booking_time import INDIA_TIMEZONE, india_now


MAX_PEOPLE_COUNT = 1000
READING_INTERVAL = timedelta(seconds=2)
MAX_FUTURE_SKEW = timedelta(minutes=2)
LIVE_WINDOW = timedelta(seconds=60)
RETENTION_DAYS = 30
DEFAULT_HISTORY_RANGE = timedelta(hours=1)
MAX_HISTORY_RANGE = timedelta(days=7)


class ReadingRejected(Exception):
    status_code = 400
    retry_after: int | None = None


class InvalidReadingError(ReadingRejected):
    status_code = 400


class SensorInactiveError(ReadingRejected):
    status_code = 403


class ReadingRateLimitError(ReadingRejected):
    status_code = 429

    def __init__(self, message: str, retry_after: int):
        super().__init__(message)
        self.retry_after = retry_after


# ---------------------------------------------------------------- time helpers


def to_india_naive(value: datetime) -> datetime:
    """Store everything as naive IST. Aware values are converted; naive values are taken as IST."""
    if value.tzinfo is None:
        return value
    return value.astimezone(INDIA_TIMEZONE).replace(tzinfo=None)


def as_india_aware(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=INDIA_TIMEZONE) if value else None


# ---------------------------------------------------------------- API keys


def hash_sensor_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


_DUMMY_KEY_HASH = hash_sensor_key(secrets.token_urlsafe(32))


def issue_sensor_key(sensor: Sensor) -> str:
    """Generate a new key of the form "<sensor id>.<secret>" and store only its hash."""
    key = f"{sensor.id}.{secrets.token_urlsafe(32)}"
    sensor.api_key_hash = hash_sensor_key(key)
    return key


def authenticate_sensor_key(db: Session, key: str | None) -> Sensor | None:
    """Return the sensor for a valid key. The sensor id prefix selects the row; the
    hash comparison is always performed, in constant time, even for unknown ids."""
    key = (key or "").strip()
    sensor_id, separator, _secret = key.partition(".")
    sensor = None
    if separator and sensor_id.isdigit() and len(sensor_id) < 12:
        sensor = db.get(Sensor, int(sensor_id))
    expected = sensor.api_key_hash if sensor else _DUMMY_KEY_HASH
    matches = hmac.compare_digest(hash_sensor_key(key), expected)
    return sensor if sensor and matches else None


# ---------------------------------------------------------------- sensor admin


def sensor_status(sensor: Sensor, now: datetime | None = None) -> str:
    now = now or india_now()
    if not sensor.is_active:
        return "inactive"
    if sensor.last_seen_at and sensor.last_seen_at >= now - LIVE_WINDOW:
        return "online"
    return "offline"


def create_sensor(
    db: Session, *, resource: Resource, name: str, is_simulated: bool
) -> tuple[Sensor, str]:
    sensor = Sensor(
        resource_id=resource.id,
        name=name.strip(),
        api_key_hash="",
        is_active=True,
        is_simulated=is_simulated,
    )
    db.add(sensor)
    db.flush()
    key = issue_sensor_key(sensor)
    db.commit()
    db.refresh(sensor)
    return sensor, key


def update_sensor(
    db: Session, sensor: Sensor, *, name: str | None, is_active: bool | None
) -> Sensor:
    if name is not None:
        sensor.name = name.strip()
    if is_active is not None:
        sensor.is_active = is_active
    db.commit()
    db.refresh(sensor)
    return sensor


def rotate_sensor_key(db: Session, sensor: Sensor) -> str:
    key = issue_sensor_key(sensor)
    db.commit()
    db.refresh(sensor)
    return key


def delete_sensor(db: Session, sensor: Sensor) -> None:
    """Delete the sensor but keep its readings as resource history."""
    db.execute(
        update(OccupancyReading)
        .where(OccupancyReading.sensor_id == sensor.id)
        .values(sensor_id=None)
        .execution_options(synchronize_session=False)
    )
    db.delete(sensor)
    db.commit()


# ---------------------------------------------------------------- ingestion


def record_reading(
    db: Session,
    *,
    sensor: Sensor,
    people_count: int,
    recorded_at: datetime | None = None,
    now: datetime | None = None,
) -> OccupancyReading:
    now = now or india_now()
    if not sensor.is_active:
        raise SensorInactiveError("Sensor is inactive.")
    if isinstance(people_count, bool) or not 0 <= people_count <= MAX_PEOPLE_COUNT:
        raise InvalidReadingError(f"People count must be between 0 and {MAX_PEOPLE_COUNT}.")
    recorded = to_india_naive(recorded_at) if recorded_at else now
    if recorded > now + MAX_FUTURE_SKEW:
        raise InvalidReadingError("Reading time is more than 2 minutes in the future.")

    # Compare-and-set: claim the 2-second window atomically so concurrent posts
    # from the same sensor cannot both succeed.
    result = db.execute(
        update(Sensor)
        .where(
            Sensor.id == sensor.id,
            Sensor.is_active.is_(True),
            or_(Sensor.last_seen_at.is_(None), Sensor.last_seen_at <= now - READING_INTERVAL),
        )
        .values(last_seen_at=now)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        current = db.get(Sensor, sensor.id)
        if not current or not current.is_active:
            raise SensorInactiveError("Sensor is inactive.")
        wait = (current.last_seen_at + READING_INTERVAL - now).total_seconds()
        raise ReadingRateLimitError(
            "Readings are limited to one every 2 seconds per sensor.",
            retry_after=max(1, math.ceil(wait)),
        )

    reading = OccupancyReading(
        sensor_id=sensor.id,
        resource_id=sensor.resource_id,
        people_count=people_count,
        recorded_at=recorded,
    )
    db.add(reading)
    db.commit()
    db.refresh(reading)
    return reading


# ---------------------------------------------------------------- read side


def smoothed_count(values: list[int]) -> int | None:
    """Median of the values, rounded half up to a whole person."""
    if not values:
        return None
    return math.floor(statistics.median(values) + 0.5)


def live_occupancy(db: Session, now: datetime | None = None) -> list[dict[str, object]]:
    now = now or india_now()
    window_start = now - LIVE_WINDOW
    resources = db.scalars(
        select(Resource).options(joinedload(Resource.zone)).order_by(Resource.name)
    ).all()

    active_sensors: dict[int, list[Sensor]] = defaultdict(list)
    for sensor in db.scalars(select(Sensor).where(Sensor.is_active.is_(True))).all():
        active_sensors[sensor.resource_id].append(sensor)

    recent_counts: dict[int, list[int]] = defaultdict(list)
    for resource_id, count in db.execute(
        select(OccupancyReading.resource_id, OccupancyReading.people_count)
        .join(Sensor, OccupancyReading.sensor_id == Sensor.id)
        .where(
            Sensor.is_active.is_(True),
            OccupancyReading.recorded_at >= window_start,
            OccupancyReading.recorded_at <= now + MAX_FUTURE_SKEW,
        )
    ).all():
        recent_counts[resource_id].append(count)

    current_bookings = {
        item.resource_id: item
        for item in db.scalars(
            select(Request).where(
                Request.status == "approved",
                Request.start <= now,
                Request.end > now,
            )
        ).all()
    }

    rows = []
    for resource in resources:
        sensors = active_sensors.get(resource.id, [])
        seen = [sensor.last_seen_at for sensor in sensors if sensor.last_seen_at]
        last_seen = max(seen) if seen else None
        if not sensors:
            status = "unsensored"
        elif last_seen and last_seen >= window_start:
            status = "online"
        else:
            status = "offline"
        booking = current_bookings.get(resource.id)
        rows.append(
            {
                "resource": resource,
                "current_booking": (
                    {
                        "request_id": booking.id,
                        "start": as_india_aware(booking.start),
                        "end": as_india_aware(booking.end),
                        "expected_attendance": booking.attendees,
                    }
                    if booking
                    else None
                ),
                "people_count": smoothed_count(recent_counts.get(resource.id, [])),
                "capacity": resource.capacity,
                "sensor_status": status,
                "last_reading_at": as_india_aware(last_seen),
                # Occupancy status (for example under-used or over capacity) arrives in a later phase.
                "status": "unknown",
            }
        )
    return rows


def resolve_history_range(
    start: datetime | None, end: datetime | None, now: datetime | None = None
) -> tuple[datetime, datetime] | str:
    now = now or india_now()
    end_value = to_india_naive(end) if end else now
    start_value = to_india_naive(start) if start else end_value - DEFAULT_HISTORY_RANGE
    if end_value <= start_value:
        return "The end of the range must be after the start."
    if end_value - start_value > MAX_HISTORY_RANGE:
        return "History can cover at most 7 days per request."
    return start_value, end_value


def occupancy_history(
    db: Session, *, resource_id: int, start: datetime, end: datetime
) -> list[dict[str, object]]:
    buckets: dict[datetime, list[int]] = defaultdict(list)
    for recorded_at, count in db.execute(
        select(OccupancyReading.recorded_at, OccupancyReading.people_count)
        .where(
            OccupancyReading.resource_id == resource_id,
            OccupancyReading.recorded_at >= start,
            OccupancyReading.recorded_at < end,
        )
        .order_by(OccupancyReading.recorded_at)
    ).all():
        buckets[recorded_at.replace(second=0, microsecond=0)].append(count)
    return [
        {
            "minute": as_india_aware(minute),
            "average_people_count": round(sum(values) / len(values), 1),
            "median_people_count": smoothed_count(values),
            "min_people_count": min(values),
            "max_people_count": max(values),
            "readings": len(values),
        }
        for minute, values in sorted(buckets.items())
    ]


# ---------------------------------------------------------------- retention


def purge_old_readings(
    db: Session, now: datetime | None = None, retention_days: int = RETENTION_DAYS
) -> int:
    """Delete readings older than the retention window. Returns the number deleted."""
    now = now or india_now()
    result = db.execute(
        delete(OccupancyReading).where(
            OccupancyReading.recorded_at < now - timedelta(days=retention_days)
        )
    )
    db.commit()
    return result.rowcount or 0
