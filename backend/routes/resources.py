from datetime import datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from backend.database import get_db
from backend.models import Request, Resource
from backend.routes.dependencies import get_current_user
from backend.routes.helpers import approval_message, request_response, resource_response
from backend.schemas import ResourceDetailResponse, SearchResponse
from backend.services.analytics import ranked_resources
from backend.services.booking import expire_pending_requests, parse_dt
from backend.services.natural_language import VagueSearchError, parse_natural_language


router = APIRouter(prefix="/api/resources", tags=["Resources"])


@router.get(
    "",
    response_model=SearchResponse,
    summary="Search and rank resources",
    description="Finds available resources and ranks quieter campus zones first.",
)
def search_resources(
    resource_type: str = Query("", alias="type"),
    attendees: int = Query(18, ge=1),
    equipment: str = "",
    start: str | None = None,
    end: str | None = None,
    q: str = "",
    show_on_hold: bool = False,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    expire_pending_requests(db)
    now = datetime.now()
    week_start = datetime.combine((now - timedelta(days=now.weekday())).date(), time.min)
    default_start = week_start + timedelta(days=2, hours=10)
    if q.strip():
        try:
            parsed = parse_natural_language(q.strip(), now)
        except VagueSearchError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        resource_type = str(parsed["type"])
        attendees = int(parsed["attendees"])
        equipment_items = list(parsed["equipment"])
        start_dt = parse_dt(f"{parsed['date']}T{parsed['start_time']}")
        end_dt = parse_dt(f"{parsed['date']}T{parsed['end_time']}")
    else:
        equipment_items = [item.strip() for item in equipment.split(",") if item.strip()]
        try:
            start_dt = parse_dt(start) if start else default_start
            end_dt = parse_dt(end) if end else default_start + timedelta(hours=1)
        except ValueError:
            raise HTTPException(status_code=400, detail="Choose a valid time range.")
    if end_dt <= start_dt:
        raise HTTPException(status_code=400, detail="Choose a valid time range.")

    ranked = ranked_resources(
        db,
        resource_type=resource_type,
        attendees=attendees,
        equipment=equipment_items,
        start=start_dt,
        end=end_dt,
        show_on_hold=show_on_hold,
    )
    results = [
        {
            "resource": resource_response(item["resource"]),
            "zone_load": item["zone_load"],
            "load_percent": item["load_percent"],
            "bar_width": item["bar_width"],
            "reason": item["reason"],
            "approval_message": approval_message(user, item["resource"]),
            "available": item["available"],
            "availability_label": item["availability_label"],
        }
        for item in ranked
    ]
    return {
        "filters": {
            "type": resource_type,
            "attendees": attendees,
            "equipment": equipment_items,
            "start": start_dt,
            "end": end_dt,
            "query": q.strip(),
            "show_on_hold": show_on_hold,
        },
        "results": results,
    }


@router.get(
    "/{resource_id}",
    response_model=ResourceDetailResponse,
    summary="Get a resource",
    description="Returns resource details, closure windows, recent requests, and approval behavior.",
)
def resource_detail(
    resource_id: int,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    expire_pending_requests(db)
    resource = db.scalars(
        select(Resource)
        .where(Resource.id == resource_id)
        .options(joinedload(Resource.zone), joinedload(Resource.unavailability))
    ).unique().first()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found.")
    recent = db.scalars(
        select(Request)
        .where(Request.resource_id == resource_id)
        .options(joinedload(Request.user), joinedload(Request.resource).joinedload(Resource.zone))
        .order_by(Request.start.desc())
        .limit(12)
    ).all()
    return {
        "resource": resource_response(resource),
        "unavailability": resource.unavailability,
        "recent_requests": [request_response(item) for item in recent],
        "approval_message": approval_message(user, resource),
    }
