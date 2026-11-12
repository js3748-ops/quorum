import unittest
from datetime import datetime, time, timedelta, timezone

from fastapi import HTTPException, Response
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import OccupancyReading, Request, Resource, Sensor, User, Zone
from backend.routes.dependencies import get_admin, get_sensor
from backend.routes.occupancy import history, live, submit_reading
from backend.routes.sensors import (
    edit_sensor,
    list_sensors,
    register_sensor,
    remove_sensor,
    rotate_key,
)
from backend.schemas import OccupancyReadingCreate, SensorCreate, SensorUpdate
from backend.services.booking_time import india_now
from backend.services.occupancy import (
    InvalidReadingError,
    ReadingRateLimitError,
    SensorInactiveError,
    live_occupancy,
    occupancy_history,
    purge_old_readings,
    record_reading,
    smoothed_count,
)


class OccupancyTestCase(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        zone = Zone(name="Tech Park North", building="Ada", floor="2")
        self.db.add(zone)
        self.db.flush()
        self.lab = Resource(
            name="AI Lab", type="lab", zone_id=zone.id, capacity=30, equipment=[],
            status="active", open_time=time(8), close_time=time(20),
        )
        self.classroom = Resource(
            name="Classroom A", type="classroom", zone_id=zone.id, capacity=40, equipment=[],
            status="active", open_time=time(8), close_time=time(20),
        )
        self.campus = User(name="Campus", role="admin", admin_scope="all")
        self.labs_admin = User(name="Labs", role="admin", admin_scope="labs")
        self.facilities = User(name="Facilities", role="admin", admin_scope="facilities")
        self.student = User(name="Student", role="student")
        self.db.add_all(
            [self.lab, self.classroom, self.campus, self.labs_admin, self.facilities, self.student]
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def register(self, resource, admin=None, name="Door counter"):
        result = register_sensor(
            SensorCreate(resource_id=resource.id, name=name),
            Response(),
            admin or self.campus,
            self.db,
        )
        return self.db.get(Sensor, result["sensor"].id), result["api_key"]

    def assert_http(self, status_code, func, *args, **kwargs):
        with self.assertRaises(HTTPException) as caught:
            func(*args, **kwargs)
        self.assertEqual(caught.exception.status_code, status_code)
        return caught.exception


class SensorKeyAuthTests(OccupancyTestCase):
    def test_valid_key_authenticates_and_only_hash_is_stored(self):
        sensor, key = self.register(self.lab)
        self.assertEqual(get_sensor(key, self.db).id, sensor.id)
        self.assertNotEqual(sensor.api_key_hash, key)
        self.assertNotIn(key.split(".", 1)[1], sensor.api_key_hash)
        self.assertEqual(len(sensor.api_key_hash), 64)

    def test_wrong_missing_and_malformed_keys_are_rejected(self):
        sensor, key = self.register(self.lab)
        for bad in [None, "", "garbage", f"{sensor.id}.wrong-secret", f"999.{key.split('.', 1)[1]}", key + "x"]:
            with self.subTest(key=bad):
                self.assert_http(401, get_sensor, bad, self.db)

    def test_inactive_sensor_cannot_submit(self):
        sensor, key = self.register(self.lab)
        edit_sensor(sensor.id, SensorUpdate(is_active=False), self.campus, self.db)
        authenticated = get_sensor(key, self.db)
        self.assert_http(403, submit_reading, OccupancyReadingCreate(people_count=3), authenticated, self.db)
        self.assertEqual(self.db.scalars(select(OccupancyReading)).all(), [])

    def test_rotated_key_replaces_old_key(self):
        sensor, old_key = self.register(self.lab)
        new_key = rotate_key(sensor.id, Response(), self.campus, self.db)["api_key"]
        self.assertNotEqual(old_key, new_key)
        self.assert_http(401, get_sensor, old_key, self.db)
        self.assertEqual(get_sensor(new_key, self.db).id, sensor.id)

    def test_key_responses_are_not_cacheable(self):
        response = Response()
        register_sensor(SensorCreate(resource_id=self.lab.id, name="Cam"), response, self.campus, self.db)
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_deleted_sensor_key_stops_working_and_history_is_kept(self):
        sensor, key = self.register(self.lab)
        record_reading(self.db, sensor=sensor, people_count=5)
        remove_sensor(sensor.id, self.campus, self.db)
        self.assert_http(401, get_sensor, key, self.db)
        reading = self.db.scalars(select(OccupancyReading)).one()
        self.assertIsNone(reading.sensor_id)
        self.assertEqual(reading.resource_id, self.lab.id)


class ReadingValidationTests(OccupancyTestCase):
    def test_schema_rejects_bad_counts_and_extra_fields(self):
        for payload in [
            {"people_count": -1},
            {"people_count": 1001},
            {"people_count": "5"},
            {"people_count": 2.5},
            {},
            {"people_count": 3, "frame": "base64-image-data"},
        ]:
            with self.subTest(payload=payload):
                with self.assertRaises(ValidationError):
                    OccupancyReadingCreate(**payload)
        self.assertEqual(OccupancyReadingCreate(people_count=1000).people_count, 1000)
        self.assertEqual(OccupancyReadingCreate(people_count=0).people_count, 0)

    def test_service_rejects_out_of_range_counts(self):
        sensor, _ = self.register(self.lab)
        for count in (-1, 1001):
            with self.assertRaises(InvalidReadingError):
                record_reading(self.db, sensor=sensor, people_count=count)

    def test_future_timestamps_beyond_two_minutes_are_rejected(self):
        sensor, _ = self.register(self.lab)
        now = datetime(2026, 11, 12, 10, 0, 0)
        with self.assertRaises(InvalidReadingError):
            record_reading(self.db, sensor=sensor, people_count=4,
                           recorded_at=now + timedelta(minutes=2, seconds=1), now=now)
        reading = record_reading(self.db, sensor=sensor, people_count=4,
                                 recorded_at=now + timedelta(minutes=1, seconds=59), now=now)
        self.assertEqual(reading.recorded_at, now + timedelta(minutes=1, seconds=59))

    def test_recorded_at_defaults_to_now_and_last_seen_is_updated(self):
        sensor, _ = self.register(self.lab)
        now = datetime(2026, 11, 12, 10, 0, 0)
        reading = record_reading(self.db, sensor=sensor, people_count=4, now=now)
        self.assertEqual(reading.recorded_at, now)
        self.db.refresh(sensor)
        self.assertEqual(sensor.last_seen_at, now)

    def test_aware_timestamps_are_stored_as_india_time(self):
        sensor, _ = self.register(self.lab)
        now = datetime(2026, 11, 12, 10, 0, 0)
        utc_time = datetime(2026, 11, 12, 4, 29, 0, tzinfo=timezone.utc)
        reading = record_reading(self.db, sensor=sensor, people_count=4, recorded_at=utc_time, now=now)
        self.assertEqual(reading.recorded_at, datetime(2026, 11, 12, 9, 59, 0))


class RateLimitTests(OccupancyTestCase):
    def test_one_reading_per_two_seconds(self):
        sensor, _ = self.register(self.lab)
        now = datetime(2026, 11, 12, 10, 0, 0)
        record_reading(self.db, sensor=sensor, people_count=1, now=now)
        with self.assertRaises(ReadingRateLimitError) as caught:
            record_reading(self.db, sensor=sensor, people_count=2, now=now + timedelta(seconds=1))
        self.assertEqual(caught.exception.retry_after, 1)
        record_reading(self.db, sensor=sensor, people_count=3, now=now + timedelta(seconds=2))
        self.assertEqual(len(self.db.scalars(select(OccupancyReading)).all()), 2)

    def test_limit_is_per_sensor(self):
        first, _ = self.register(self.lab, name="A")
        second, _ = self.register(self.lab, name="B")
        now = datetime(2026, 11, 12, 10, 0, 0)
        record_reading(self.db, sensor=first, people_count=1, now=now)
        record_reading(self.db, sensor=second, people_count=1, now=now)

    def test_endpoint_returns_429_with_retry_after(self):
        _, key = self.register(self.lab)
        sensor = get_sensor(key, self.db)
        submit_reading(OccupancyReadingCreate(people_count=1), sensor, self.db)
        error = self.assert_http(429, submit_reading, OccupancyReadingCreate(people_count=2), sensor, self.db)
        self.assertIn("Retry-After", error.headers)

    def test_deactivated_sensor_is_reported_as_inactive_not_rate_limited(self):
        sensor, _ = self.register(self.lab)
        now = datetime(2026, 11, 12, 10, 0, 0)
        record_reading(self.db, sensor=sensor, people_count=1, now=now)
        sensor.is_active = False
        self.db.commit()
        with self.assertRaises(SensorInactiveError):
            record_reading(self.db, sensor=sensor, people_count=1, now=now + timedelta(seconds=5))


class AdminScopeTests(OccupancyTestCase):
    def test_non_admin_is_refused(self):
        self.assert_http(403, get_admin, self.student)

    def test_create_requires_scope_over_resource(self):
        self.register(self.lab, admin=self.labs_admin)
        self.assert_http(404, register_sensor, SensorCreate(resource_id=self.classroom.id, name="X"),
                         Response(), self.labs_admin, self.db)
        self.assert_http(404, register_sensor, SensorCreate(resource_id=self.lab.id, name="X"),
                         Response(), self.facilities, self.db)
        self.assert_http(404, register_sensor, SensorCreate(resource_id=999, name="X"),
                         Response(), self.campus, self.db)

    def test_list_is_scoped(self):
        lab_sensor, _ = self.register(self.lab)
        room_sensor, _ = self.register(self.classroom)

        def ids(admin):
            return {item.id for item in list_sensors(admin, self.db)["sensors"]}

        self.assertEqual(ids(self.campus), {lab_sensor.id, room_sensor.id})
        self.assertEqual(ids(self.labs_admin), {lab_sensor.id})
        self.assertEqual(ids(self.facilities), {room_sensor.id})
        listed = list_sensors(self.labs_admin, self.db)["sensors"][0]
        self.assertEqual(listed.resource_name, "AI Lab")
        self.assertEqual(listed.status, "offline")
        self.assertIsNone(listed.last_seen_at)

    def test_out_of_scope_sensor_actions_return_404(self):
        sensor, key = self.register(self.lab)
        self.assert_http(404, edit_sensor, sensor.id, SensorUpdate(name="New"), self.facilities, self.db)
        self.assert_http(404, rotate_key, sensor.id, Response(), self.facilities, self.db)
        self.assert_http(404, remove_sensor, sensor.id, self.facilities, self.db)
        self.assertEqual(get_sensor(key, self.db).name, "Door counter")

    def test_in_scope_admin_can_rename_and_toggle(self):
        sensor, _ = self.register(self.lab)
        renamed = edit_sensor(sensor.id, SensorUpdate(name="  Rear door "), self.labs_admin, self.db)
        self.assertEqual(renamed.name, "Rear door")
        disabled = edit_sensor(sensor.id, SensorUpdate(is_active=False), self.labs_admin, self.db)
        self.assertEqual(disabled.status, "inactive")
        with self.assertRaises(ValidationError):
            SensorUpdate()


class LiveOccupancyTests(OccupancyTestCase):
    def add_reading(self, sensor, count, at):
        self.db.add(OccupancyReading(sensor_id=sensor.id, resource_id=sensor.resource_id,
                                     people_count=count, recorded_at=at))

    def test_smoothing_is_median_rounded_half_up(self):
        self.assertIsNone(smoothed_count([]))
        self.assertEqual(smoothed_count([4, 6, 50]), 6)
        self.assertEqual(smoothed_count([3, 4]), 4)
        self.assertEqual(smoothed_count([2, 100, 3, 1]), 3)

    def test_live_uses_median_of_last_60_seconds_and_sensor_status(self):
        now = datetime(2026, 11, 12, 10, 0, 0)
        sensor, _ = self.register(self.lab)
        self.add_reading(sensor, 100, now - timedelta(seconds=70))
        self.add_reading(sensor, 4, now - timedelta(seconds=50))
        self.add_reading(sensor, 6, now - timedelta(seconds=30))
        self.add_reading(sensor, 50, now - timedelta(seconds=10))
        sensor.last_seen_at = now - timedelta(seconds=10)
        self.db.add(Request(user_id=self.student.id, resource_id=self.lab.id,
                            start=now - timedelta(minutes=30), end=now + timedelta(minutes=30),
                            attendees=12, purpose="Weekly lab practical", status="approved"))
        self.db.commit()

        rows = {row["resource"].id: row for row in live_occupancy(self.db, now)}
        lab = rows[self.lab.id]
        self.assertEqual(lab["people_count"], 6)
        self.assertEqual(lab["sensor_status"], "online")
        self.assertEqual(lab["capacity"], 30)
        self.assertEqual(lab["status"], "unknown")
        self.assertEqual(lab["current_booking"]["expected_attendance"], 12)

        room = rows[self.classroom.id]
        self.assertEqual(room["sensor_status"], "unsensored")
        self.assertIsNone(room["people_count"])
        self.assertIsNone(room["current_booking"])

    def test_stale_and_inactive_sensors(self):
        now = datetime(2026, 11, 12, 10, 0, 0)
        sensor, _ = self.register(self.lab)
        self.add_reading(sensor, 9, now - timedelta(seconds=90))
        sensor.last_seen_at = now - timedelta(seconds=90)
        self.db.commit()
        lab = {r["resource"].id: r for r in live_occupancy(self.db, now)}[self.lab.id]
        self.assertEqual(lab["sensor_status"], "offline")
        self.assertIsNone(lab["people_count"])

        self.add_reading(sensor, 9, now - timedelta(seconds=5))
        sensor.is_active = False
        self.db.commit()
        lab = {r["resource"].id: r for r in live_occupancy(self.db, now)}[self.lab.id]
        self.assertEqual(lab["sensor_status"], "unsensored")
        self.assertIsNone(lab["people_count"])

    def test_pending_bookings_are_not_current(self):
        now = datetime(2026, 11, 12, 10, 0, 0)
        self.db.add(Request(user_id=self.student.id, resource_id=self.lab.id,
                            start=now - timedelta(minutes=30), end=now + timedelta(minutes=30),
                            attendees=12, purpose="Weekly lab practical", status="pending"))
        self.db.commit()
        lab = {r["resource"].id: r for r in live_occupancy(self.db, now)}[self.lab.id]
        self.assertIsNone(lab["current_booking"])

    def test_live_endpoint_serializes(self):
        sensor, _ = self.register(self.lab)
        record_reading(self.db, sensor=sensor, people_count=7)
        result = live(self.student, self.db)
        lab = next(item for item in result["resources"] if item["resource"].id == self.lab.id)
        self.assertEqual(lab["people_count"], 7)
        self.assertEqual(lab["sensor_status"], "online")


class HistoryAndRetentionTests(OccupancyTestCase):
    def test_history_buckets_per_minute(self):
        sensor, _ = self.register(self.lab)
        base = datetime(2026, 11, 12, 10, 0, 0)
        for seconds, count in [(5, 2), (20, 4), (55, 9), (65, 1)]:
            self.db.add(OccupancyReading(sensor_id=sensor.id, resource_id=self.lab.id,
                                         people_count=count, recorded_at=base + timedelta(seconds=seconds)))
        self.db.commit()
        buckets = occupancy_history(self.db, resource_id=self.lab.id,
                                    start=base, end=base + timedelta(minutes=5))
        self.assertEqual(len(buckets), 2)
        self.assertEqual(buckets[0]["minute"].replace(tzinfo=None), base)
        self.assertEqual(buckets[0]["readings"], 3)
        self.assertEqual(buckets[0]["average_people_count"], 5.0)
        self.assertEqual(buckets[0]["median_people_count"], 4)
        self.assertEqual((buckets[0]["min_people_count"], buckets[0]["max_people_count"]), (2, 9))
        self.assertEqual(buckets[1]["readings"], 1)

    def test_history_endpoint_validates_range_and_resource(self):
        now = india_now()
        self.assert_http(404, history, 999, None, None, self.student, self.db)
        self.assert_http(400, history, self.lab.id, now, now - timedelta(minutes=1), self.student, self.db)
        self.assert_http(400, history, self.lab.id, now - timedelta(days=8), now, self.student, self.db)
        result = history(self.lab.id, None, None, self.student, self.db)
        self.assertEqual(result["buckets"], [])
        self.assertEqual(result["end"] - result["start"], timedelta(hours=1))

    def test_purge_deletes_readings_older_than_30_days(self):
        sensor, _ = self.register(self.lab)
        now = datetime(2026, 11, 12, 10, 0, 0)
        for age in (timedelta(days=31), timedelta(days=30, seconds=1), timedelta(days=29)):
            self.db.add(OccupancyReading(sensor_id=sensor.id, resource_id=self.lab.id,
                                         people_count=1, recorded_at=now - age))
        self.db.commit()
        self.assertEqual(purge_old_readings(self.db, now), 2)
        remaining = self.db.scalars(select(OccupancyReading)).all()
        self.assertEqual([r.recorded_at for r in remaining], [now - timedelta(days=29)])


if __name__ == "__main__":
    unittest.main()
