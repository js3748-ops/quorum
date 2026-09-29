from datetime import datetime, time, timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import BookingSlot, Request, Resource, Unavailability

SLOT_MINUTES = 30


def parse_dt(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M")


def slots_between(start: datetime, end: datetime) -> list[datetime]:
    slots = []
    current = start
    while current < end:
        slots.append(current)
        current += timedelta(minutes=SLOT_MINUTES)
    return slots


def is_slot_boundary(dt: datetime) -> bool:
    return dt.second == 0 and dt.microsecond == 0 and dt.minute in (0, 30)


def format_window(start: datetime, end: datetime) -> str:
    return f"{start:%H:%M}-{end:%H:%M}"


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


def validate_request_window(resource: Resource, start: datetime, end: datetime) -> str | None:
    if end <= start:
        return "End time must be after start time."
    if not is_slot_boundary(start) or not is_slot_boundary(end):
        return "Bookings must start and end on 30-minute boundaries."
    if start.time() < resource.open_time or end.time() > resource.close_time:
        return f"{resource.name} is open {resource.open_time:%H:%M}-{resource.close_time:%H:%M}."
    if resource.status != "active":
        return f"{resource.name} is not active."
    return None


def find_conflict(db: Session, resource: Resource, start: datetime, end: datetime) -> str | None:
    base_error = validate_request_window(resource, start, end)
    if base_error:
        return base_error

    unavailable = db.scalars(
        select(Unavailability).where(
            Unavailability.resource_id == resource.id,
            Unavailability.start < end,
            Unavailability.end > start,
        )
    ).first()
    if unavailable:
        return f"Closed for {unavailable.reason} {format_window(unavailable.start, unavailable.end)}."

    slot_starts = slots_between(start, end)
    booked_slot = db.scalars(
        select(BookingSlot).where(
            BookingSlot.resource_id == resource.id,
            BookingSlot.slot_start.in_(slot_starts),
        )
    ).first()
    if booked_slot:
        booked = booked_slot.request
        return f"Booked {format_window(booked.start, booked.end)} by another request."

    return None


def create_booking_request(
    db: Session,
    *,
    user_id: int,
    resource: Resource,
    start: datetime,
    end: datetime,
    attendees: int,
    purpose: str,
) -> tuple[Request | None, str | None]:
    conflict = find_conflict(db, resource, start, end)
    if conflict:
        return None, conflict

    status = "pending" if resource.requires_approval else "approved"
    request = Request(
        user_id=user_id,
        resource_id=resource.id,
        start=start,
        end=end,
        attendees=attendees,
        purpose=purpose.strip() or "Booking",
        status=status,
    )
    db.add(request)
    db.flush()
    for slot_start in slots_between(start, end):
        db.add(
            BookingSlot(
                request_id=request.id,
                resource_id=resource.id,
                slot_start=slot_start,
            )
        )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None, "This slot was just booked by another request."
    db.refresh(request)
    return request, None


def decide_request(
    db: Session,
    *,
    booking_request: Request,
    admin_id: int,
    decision: str,
    rejection_note: str = "",
) -> str | None:
    if booking_request.status != "pending":
        return f"Request #{booking_request.id} has already been decided."
    if decision not in {"approved", "rejected"}:
        return "Invalid decision."

    booking_request.status = decision
    booking_request.decided_by = admin_id
    booking_request.decided_at = datetime.now()
    booking_request.rejection_note = rejection_note.strip() or None
    if decision == "rejected":
        db.execute(delete(BookingSlot).where(BookingSlot.request_id == booking_request.id))
    db.commit()
    return None


def nearest_free_times(
    db: Session,
    resource: Resource,
    start: datetime,
    end: datetime,
    limit: int = 3,
) -> list[dict[str, object]]:
    duration = end - start
    options = []
    offsets = [30, -30, 60, -60, 90, -90, 120, -120, 180, -180, 240, -240]
    for minutes in offsets:
        candidate_start = start + timedelta(minutes=minutes)
        candidate_end = candidate_start + duration
        if candidate_start.date() != start.date():
            continue
        if not find_conflict(db, resource, candidate_start, candidate_end):
            options.append(
                {
                    "resource": resource,
                    "start": candidate_start,
                    "end": candidate_end,
                    "kind": "Same resource",
                }
            )
        if len(options) >= limit:
            break
    return options


def similar_resources(
    db: Session,
    resource: Resource,
    start: datetime,
    end: datetime,
    attendees: int,
    limit: int = 3,
) -> list[dict[str, object]]:
    needed_equipment = set(resource.equipment or [])
    resources = db.scalars(
        select(Resource).where(
            Resource.id != resource.id,
            Resource.status == "active",
            Resource.type == resource.type,
            Resource.capacity >= attendees,
        )
    ).all()
    matches = []
    for candidate in resources:
        candidate_equipment = set(candidate.equipment or [])
        if not needed_equipment.issubset(candidate_equipment):
            continue
        if not find_conflict(db, candidate, start, end):
            matches.append(
                {
                    "resource": candidate,
                    "start": start,
                    "end": end,
                    "kind": "Similar resource",
                }
            )
        if len(matches) >= limit:
            break
    return matches


def suggest_alternatives(
    db: Session,
    resource: Resource,
    start: datetime,
    end: datetime,
    attendees: int,
) -> list[dict[str, object]]:
    suggestions = nearest_free_times(db, resource, start, end, limit=3)
    remaining = 3 - len(suggestions)
    if remaining > 0:
        suggestions.extend(similar_resources(db, resource, start, end, attendees, remaining))
    return suggestions[:3]


def parse_time(value: str) -> time:
    return datetime.strptime(value, "%H:%M").time()
