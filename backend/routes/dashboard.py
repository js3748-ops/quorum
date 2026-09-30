from datetime import datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from backend.database import get_db
from backend.models import Request, Resource, User
from backend.routes.dependencies import get_admin, get_current_user
from backend.routes.helpers import request_response, resource_response
from backend.schemas import AdminHomeResponse, DashboardResponse, UserDashboardResponse
from backend.services.admin_scope import scope_resource_query
from backend.services.analytics import current_week_dashboard, current_zone_loads
from backend.services.booking import expire_pending_requests, india_now


router = APIRouter(prefix="/api/admin", tags=["Analytics"])
user_router = APIRouter(prefix="/api", tags=["Dashboard"])


@user_router.get(
    "/dashboard",
    response_model=UserDashboardResponse,
    summary="Get my booking dashboard",
    description="Returns upcoming bookings, pending requests, decisions, current zone loads, and hold notices.",
)
def user_dashboard(user=Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role == "admin":
        raise HTTPException(status_code=403, detail="Use the administrator home.")
    expire_pending_requests(db)
    now = india_now()
    base = (
        select(Request)
        .where(Request.user_id == user.id)
        .options(
            joinedload(Request.user),
            joinedload(Request.decider),
            joinedload(Request.resource).joinedload(Resource.zone),
        )
    )
    upcoming = db.scalars(
        base.where(Request.status == "approved", Request.start >= now)
        .order_by(Request.start, Request.id)
    ).all()
    pending = db.scalars(
        base.where(Request.status == "pending")
        .order_by(Request.created_at.desc(), Request.id.desc())
    ).all()
    recent = db.scalars(
        base.where(Request.status.in_(("approved", "rejected", "cancelled", "expired")))
        .order_by(func.coalesce(Request.decided_at, Request.created_at).desc(), Request.id.desc())
        .limit(5)
    ).all()
    holds = db.scalars(
        select(Resource)
        .where(Resource.status == "on_hold")
        .options(joinedload(Resource.zone))
        .order_by(Resource.name)
    ).all()
    return {
        "upcoming": [request_response(item) for item in upcoming],
        "pending": [request_response(item) for item in pending],
        "recent_decisions": [request_response(item) for item in recent],
        "quieter_zones": current_zone_loads(db, now),
        "holds": [resource_response(item) for item in holds],
    }


@router.get(
    "/home",
    response_model=AdminHomeResponse,
    summary="Get administrator home",
    description="Returns scoped pending work, today's decision counts, and resources currently on hold.",
)
def admin_home(admin=Depends(get_admin), db: Session = Depends(get_db)):
    expire_pending_requests(db)
    now = india_now()
    cutoff = datetime.utcnow() - timedelta(hours=1)
    pending_query = (
        select(Request)
        .join(Request.user)
        .join(Request.resource)
        .where(Request.status == "pending", User.role != "background")
        .options(joinedload(Request.user), joinedload(Request.resource).joinedload(Resource.zone))
        .order_by(Request.created_at.desc(), Request.id.desc())
    )
    pending = db.scalars(scope_resource_query(pending_query, admin)).all()
    day_start = datetime.combine(now.date(), time.min)
    day_end = day_start + timedelta(days=1)
    utc_day_start = day_start - timedelta(hours=5, minutes=30)
    utc_day_end = day_end - timedelta(hours=5, minutes=30)
    counts = {}
    for status in ("pending", "approved", "rejected"):
        date_column = Request.created_at if status == "pending" else Request.decided_at
        range_start = utc_day_start if status == "pending" else day_start
        range_end = utc_day_end if status == "pending" else day_end
        count_query = (
            select(func.count(Request.id))
            .join(Request.user)
            .join(Request.resource)
            .where(
                User.role != "background",
                Request.status == status,
                date_column >= range_start,
                date_column < range_end,
            )
        )
        counts[status] = db.scalar(scope_resource_query(count_query, admin)) or 0
    hold_query = (
        select(Resource)
        .where(Resource.status == "on_hold")
        .options(joinedload(Resource.zone))
        .order_by(Resource.name)
    )
    holds = db.scalars(scope_resource_query(hold_query, admin)).all()
    return {
        "pending": [
            request_response(item).model_dump() | {"is_new": item.created_at >= cutoff}
            for item in pending
        ],
        "today_counts": counts,
        "holds": [resource_response(item) for item in holds],
    }


@router.get(
    "/dashboard",
    response_model=DashboardResponse,
    summary="Get utilization analytics",
    description="Returns weekly request counts, peak hours, zone load, and resource utilization.",
)
def dashboard(admin=Depends(get_admin), db: Session = Depends(get_db)):
    expire_pending_requests(db)
    return current_week_dashboard(db)
