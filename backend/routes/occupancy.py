from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Resource
from backend.routes.dependencies import get_current_user, get_sensor
from backend.routes.helpers import resource_response
from backend.schemas import (
    LiveOccupancyResponse,
    OccupancyHistoryResponse,
    OccupancyReadingCreate,
    OccupancyReadingResponse,
)
from backend.services.booking_time import india_now
from backend.services.occupancy import (
    ReadingRejected,
    as_india_aware,
    live_occupancy,
    occupancy_history,
    record_reading,
    resolve_history_range,
)


router = APIRouter(prefix="/api/occupancy", tags=["Occupancy"])


@router.post(
    "/readings",
    response_model=OccupancyReadingResponse,
    status_code=201,
    summary="Submit a people count",
    description=(
        "Sensor endpoint authenticated by the X-Sensor-Key header. Accepts only a people count "
        "and an optional timestamp, at most one reading every 2 seconds per sensor."
    ),
)
def submit_reading(
    payload: OccupancyReadingCreate,
    sensor=Depends(get_sensor),
    db: Session = Depends(get_db),
):
    try:
        reading = record_reading(
            db,
            sensor=sensor,
            people_count=payload.people_count,
            recorded_at=payload.recorded_at,
        )
    except ReadingRejected as exc:
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        raise HTTPException(status_code=exc.status_code, detail=str(exc), headers=headers)
    return {
        "id": reading.id,
        "sensor_id": reading.sensor_id,
        "resource_id": reading.resource_id,
        "people_count": reading.people_count,
        "recorded_at": as_india_aware(reading.recorded_at),
    }


@router.get(
    "/live",
    response_model=LiveOccupancyResponse,
    summary="Get live occupancy",
    description=(
        "For every resource: the current approved booking, the smoothed people count "
        "(median of the last 60 seconds), capacity, and sensor status."
    ),
)
def live(user=Depends(get_current_user), db: Session = Depends(get_db)):
    now = india_now()
    rows = live_occupancy(db, now)
    return {
        "generated_at": as_india_aware(now),
        "resources": [row | {"resource": resource_response(row["resource"])} for row in rows],
    }


@router.get(
    "/{resource_id}/history",
    response_model=OccupancyHistoryResponse,
    summary="Get occupancy history",
    description="Returns a resource's readings bucketed per minute. Defaults to the last hour; at most 7 days.",
)
def history(
    resource_id: int,
    start: datetime | None = Query(None, alias="from"),
    end: datetime | None = Query(None, alias="to"),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not db.get(Resource, resource_id):
        raise HTTPException(status_code=404, detail="Resource not found.")
    window = resolve_history_range(start, end)
    if isinstance(window, str):
        raise HTTPException(status_code=400, detail=window)
    range_start, range_end = window
    return {
        "resource_id": resource_id,
        "start": as_india_aware(range_start),
        "end": as_india_aware(range_end),
        "buckets": occupancy_history(
            db, resource_id=resource_id, start=range_start, end=range_end
        ),
    }
