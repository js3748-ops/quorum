from collections import defaultdict
from datetime import datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.models import Request, Resource, Zone
from app.services import find_conflict


ACTIVE_REQUEST_STATUSES = ("pending", "approved")


def zone_loads(db: Session, start: datetime, end: datetime) -> dict[int, float]:
    capacities = dict(
        db.execute(
            select(Resource.zone_id, func.sum(Resource.capacity))
            .where(Resource.status == "active")
            .group_by(Resource.zone_id)
        ).all()
    )
    attendees = dict(
        db.execute(
            select(Resource.zone_id, func.sum(Request.attendees))
            .join(Request.resource)
            .where(
                Request.status.in_(ACTIVE_REQUEST_STATUSES),
                Request.start < end,
                Request.end > start,
            )
            .group_by(Resource.zone_id)
        ).all()
    )
    return {
        zone_id: attendees.get(zone_id, 0) / capacity if capacity else 0.0
        for zone_id, capacity in capacities.items()
    }


def ranked_resources(
    db: Session,
    *,
    resource_type: str,
    attendees: int,
    equipment: list[str],
    start: datetime,
    end: datetime,
) -> list[dict[str, object]]:
    query = (
        select(Resource)
        .where(Resource.status == "active", Resource.capacity >= attendees)
        .options(joinedload(Resource.zone))
    )
    if resource_type:
        query = query.where(Resource.type == resource_type)

    loads = zone_loads(db, start, end)
    needed_equipment = {item.lower() for item in equipment}
    results = []
    for resource in db.scalars(query).all():
        available_equipment = {item.lower() for item in resource.equipment or []}
        if not needed_equipment.issubset(available_equipment):
            continue
        if find_conflict(db, resource, start, end):
            continue

        load = loads.get(resource.zone_id, 0.0)
        wasted_capacity = (resource.capacity - attendees) / resource.capacity
        congestion_penalty = load * 35 + max(0.0, load - 0.6) * 180
        score = wasted_capacity * 40 + congestion_penalty
        if load > 0.6:
            reason = f"{resource.zone.name} at {load:.0%}, ranked lower"
        elif load <= 0.3:
            reason = "Quieter zone"
        else:
            reason = "Moderate zone load"
        results.append(
            {
                "resource": resource,
                "zone_load": load,
                "load_percent": round(load * 100),
                "bar_width": min(round(load * 100), 100),
                "reason": reason,
                "score": score,
            }
        )

    return sorted(results, key=lambda item: (item["score"], item["resource"].capacity))


def current_week_dashboard(db: Session, now: datetime | None = None) -> dict[str, object]:
    now = now or datetime.now()
    week_start = datetime.combine((now - timedelta(days=now.weekday())).date(), time.min)
    week_end = week_start + timedelta(days=7)
    resources = db.scalars(
        select(Resource).options(joinedload(Resource.zone)).order_by(Resource.name)
    ).all()
    requests = db.scalars(
        select(Request)
        .where(
            Request.status.in_(ACTIVE_REQUEST_STATUSES),
            Request.start < week_end,
            Request.end > week_start,
        )
        .options(joinedload(Request.resource))
    ).all()

    resource_hours = defaultdict(float)
    for item in requests:
        overlap_start = max(item.start, week_start)
        overlap_end = min(item.end, week_end)
        resource_hours[item.resource_id] += (overlap_end - overlap_start).total_seconds() / 3600

    resource_rows = []
    zone_booked = defaultdict(float)
    zone_open = defaultdict(float)
    for resource in resources:
        daily_open = (
            datetime.combine(now.date(), resource.close_time)
            - datetime.combine(now.date(), resource.open_time)
        ).total_seconds() / 3600
        open_hours = daily_open * 7 if resource.status == "active" else 0
        booked_hours = resource_hours.get(resource.id, 0.0)
        utilization = booked_hours / open_hours if open_hours else 0.0
        resource_rows.append(
            {
                "resource": resource,
                "booked_hours": booked_hours,
                "open_hours": open_hours,
                "utilization": utilization,
                "percent": round(utilization * 100),
            }
        )
        zone_booked[resource.zone_id] += booked_hours
        zone_open[resource.zone_id] += open_hours

    zones = db.scalars(select(Zone).order_by(Zone.name)).all()
    zone_rows = []
    for zone in zones:
        utilization = zone_booked[zone.id] / zone_open[zone.id] if zone_open[zone.id] else 0.0
        zone_rows.append(
            {
                "zone": zone,
                "booked_hours": zone_booked[zone.id],
                "open_hours": zone_open[zone.id],
                "utilization": utilization,
                "percent": round(utilization * 100),
            }
        )
    zone_rows.sort(key=lambda item: item["utilization"], reverse=True)

    slots = []
    cursor = datetime.combine(week_start.date(), time(8, 0))
    while cursor.time() < time(20, 0):
        slots.append(cursor.time())
        cursor += timedelta(minutes=30)

    peak_rows = []
    active_resource_count = sum(resource.status == "active" for resource in resources)
    for day_offset in range(7):
        day_start = week_start + timedelta(days=day_offset)
        cells = []
        for slot_time in slots:
            slot_start = datetime.combine(day_start.date(), slot_time)
            slot_end = slot_start + timedelta(minutes=30)
            booked_count = sum(item.start < slot_end and item.end > slot_start for item in requests)
            load = booked_count / active_resource_count if active_resource_count else 0.0
            cells.append(
                {
                    "percent": round(load * 100),
                    "intensity": f"{max(0.06, min(0.9, load * 3.5)):.2f}",
                    "booked_count": booked_count,
                    "label": slot_start.strftime("%a %H:%M"),
                }
            )
        peak_rows.append({"day": day_start.strftime("%a"), "cells": cells})

    counts = dict(db.execute(select(Request.status, func.count()).group_by(Request.status)).all())
    used_rows = sorted(resource_rows, key=lambda item: item["booked_hours"], reverse=True)
    return {
        "week_start": week_start,
        "week_last_day": week_end - timedelta(days=1),
        "counts": {status: counts.get(status, 0) for status in ("pending", "approved", "rejected")},
        "resource_rows": resource_rows,
        "zone_rows": zone_rows,
        "peak_rows": peak_rows,
        "slot_labels": [value.strftime("%H:%M") for value in slots],
        "most_used": used_rows[0] if used_rows else None,
        "least_used": used_rows[-1] if used_rows else None,
    }
