from datetime import datetime, time, timedelta
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models import BookingSlot, Request, Resource, Unavailability, User, Zone  # noqa: E402
from app.services import slots_between  # noqa: E402


def week_start(today: datetime) -> datetime:
    base = today - timedelta(days=today.weekday())
    return datetime.combine(base.date(), time(0, 0))


def main():
    random.seed(42)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        zones = [
            Zone(name="Tech Park North", building="Ada Building", floor="2"),
            Zone(name="Library West", building="Bose Library", floor="1"),
            Zone(name="Arts Court", building="Tagore Hall", floor="G"),
            Zone(name="Science Quadrant", building="Raman Block", floor="3"),
            Zone(name="Central Commons", building="Assembly Centre", floor="1"),
        ]
        db.add_all(zones)
        db.flush()

        users = [
            User(name="Asha Mehta", role="student"),
            User(name="Kabir Rao", role="student"),
            User(name="Nila Shah", role="student"),
            User(name="Dev Sen", role="student"),
            User(name="Prof. Ananya Iyer", role="faculty"),
            User(name="Prof. Rohan Das", role="faculty"),
            User(name="Mira Kapoor", role="faculty"),
            User(name="Campus Admin", role="admin"),
        ]
        db.add_all(users)
        db.flush()

        resource_specs = [
            ("AI Lab 201", "lab", 0, 36, ["projector", "linux", "gpu"], True),
            ("Systems Lab 204", "lab", 0, 32, ["linux", "projector"], True),
            ("Data Studio 212", "lab", 0, 24, ["gpu", "whiteboard"], True),
            ("North Classroom 2A", "classroom", 0, 70, ["projector"], False),
            ("North Seminar 2B", "seminar_hall", 0, 90, ["projector", "mic"], True),
            ("Quiet Room L1", "classroom", 1, 28, ["whiteboard"], False),
            ("Library Seminar", "seminar_hall", 1, 48, ["projector", "video"], True),
            ("Archive Study", "classroom", 1, 18, ["whiteboard"], False),
            ("Media Cart L", "equipment", 1, 1, ["camera", "tripod"], False),
            ("Reading Annex", "classroom", 1, 36, ["projector"], False),
            ("Black Box Hall", "seminar_hall", 2, 110, ["mic", "stage"], True),
            ("Design Studio", "lab", 2, 26, ["projector", "mac"], True),
            ("Crit Room A", "classroom", 2, 22, ["display"], False),
            ("Drawing Lab", "lab", 2, 30, ["scanner"], True),
            ("Portable PA", "equipment", 2, 1, ["mic", "speaker"], False),
            ("Chem Lab 3", "lab", 3, 34, ["fume_hood", "projector"], True),
            ("Physics Lab 301", "lab", 3, 40, ["oscilloscope", "projector"], True),
            ("Science Classroom", "classroom", 3, 60, ["projector"], False),
            ("Raman Seminar", "seminar_hall", 3, 72, ["projector", "mic"], True),
            ("Sensor Kit", "equipment", 3, 1, ["sensors"], False),
            ("Commons Hall", "seminar_hall", 4, 140, ["projector", "mic", "video"], True),
            ("Commons Classroom A", "classroom", 4, 44, ["projector"], False),
            ("Commons Classroom B", "classroom", 4, 44, ["projector"], False),
            ("Workshop Room", "lab", 4, 20, ["tools", "whiteboard"], True),
            ("Event Camera", "equipment", 4, 1, ["camera"], False),
        ]

        resources = []
        for name, kind, zone_idx, capacity, equipment, approval in resource_specs:
            resources.append(
                Resource(
                    name=name,
                    type=kind,
                    zone_id=zones[zone_idx].id,
                    capacity=capacity,
                    equipment=equipment,
                    requires_approval=approval,
                    status="active",
                    open_time=time(8, 0),
                    close_time=time(20, 0),
                )
            )
        db.add_all(resources)
        db.flush()

        start_of_week = week_start(datetime.now())
        db.add_all(
            [
                Unavailability(
                    resource_id=resources[1].id,
                    start=start_of_week + timedelta(days=2, hours=13),
                    end=start_of_week + timedelta(days=2, hours=16),
                    reason="maintenance",
                ),
                Unavailability(
                    resource_id=resources[10].id,
                    start=start_of_week + timedelta(days=4, hours=9),
                    end=start_of_week + timedelta(days=4, hours=12),
                    reason="stage inspection",
                ),
            ]
        )

        demo_start = start_of_week + timedelta(days=2, hours=10)
        demo_end = demo_start + timedelta(hours=1)
        peak_specs = [
            (resources[0], 34, "Advanced AI lab"),
            (resources[1], 30, "Systems practical"),
            (resources[3], 65, "Core lecture"),
            (resources[4], 84, "Department seminar"),
        ]
        for index, (resource, attendees, purpose) in enumerate(peak_specs):
            req = Request(
                user_id=users[index % len(users[:-1])].id,
                resource_id=resource.id,
                start=demo_start,
                end=demo_end,
                attendees=attendees,
                purpose=purpose,
                status="pending" if index == 0 else "approved",
            )
            db.add(req)
            db.flush()
            for slot_start in slots_between(demo_start, demo_end):
                db.add(
                    BookingSlot(
                        request_id=req.id,
                        resource_id=resource.id,
                        slot_start=slot_start,
                    )
                )

        busy_resources = resources[:5]
        other_resources = resources[5:]
        booking_count = len(peak_specs)
        attempts = 0
        while booking_count < 60 and attempts < 500:
            attempts += 1
            day = random.randint(0, 4)
            resource = random.choice(busy_resources if booking_count < 35 else other_resources)
            hour = random.choice([9, 9, 10, 10, 11, 14, 15, 16])
            minute = random.choice([0, 30])
            duration_slots = random.choice([1, 2, 2, 3])
            start = start_of_week + timedelta(days=day, hours=hour, minutes=minute)
            end = start + timedelta(minutes=30 * duration_slots)
            if end.time() > resource.close_time:
                continue
            if start < demo_end and end > demo_start:
                continue
            slot_values = slots_between(start, end)
            existing = {
                slot.slot_start
                for slot in db.query(BookingSlot)
                .filter(BookingSlot.resource_id == resource.id, BookingSlot.slot_start.in_(slot_values))
                .all()
            }
            if existing:
                continue
            req = Request(
                user_id=random.choice(users[:-1]).id,
                resource_id=resource.id,
                start=start,
                end=end,
                attendees=random.randint(4, max(5, min(resource.capacity, 55))),
                purpose=random.choice(
                    ["Tutorial", "Project meeting", "Guest lecture", "Lab session", "Review"]
                ),
                status="approved" if booking_count % 7 else "pending",
            )
            db.add(req)
            db.flush()
            for slot_start in slot_values:
                db.add(
                    BookingSlot(
                        request_id=req.id,
                        resource_id=resource.id,
                        slot_start=slot_start,
                    )
                )
            booking_count += 1

        for index in range(4):
            rejected_start = start_of_week + timedelta(days=index, hours=18)
            db.add(
                Request(
                    user_id=users[index].id,
                    resource_id=resources[10 + index].id,
                    start=rejected_start,
                    end=rejected_start + timedelta(hours=1),
                    attendees=10 + index,
                    purpose="Declined event request",
                    status="rejected",
                    decided_by=users[-1].id,
                    decided_at=start_of_week,
                    rejection_note="Seeded dashboard example",
                )
            )

        db.commit()
        print(
            f"Seeded {len(zones)} zones, {len(resources)} resources, "
            f"{len(users)} users, {booking_count} bookings, and 4 rejected requests."
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
