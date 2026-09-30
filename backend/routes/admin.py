import csv
from datetime import date, datetime, time, timedelta
from io import StringIO

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from backend.database import get_db
from backend.models import BookingSlot, Request, RequestEvent, Resource, Unavailability, User, Zone
from backend.routes.dependencies import get_admin, get_campus_admin
from backend.routes.helpers import request_response, resource_response
from backend.schemas import (
    AdminRequestListResponse,
    AdminHistoryResponse,
    AdminRequestDetailResponse,
    AdminResourcesResponse,
    AdminUserListResponse,
    AdminUserUpdate,
    BookingExtension,
    BookingRequestResponse,
    PendingListResponse,
    RejectRequest,
    ResourceCreate,
    ResourceHoldCreate,
    ResourceResponse,
    ResourceUpdate,
    UnavailabilityCreate,
    UserResponse,
)
from backend.services.analytics import zone_loads
from backend.services.admin_scope import admin_can_access_resource, scope_resource_query
from backend.services.booking import (
    decide_request,
    extend_booking_request,
    expire_pending_requests,
    request_slot_is_free,
    validate_request_window,
    india_now,
)
from backend.services.request_events import add_request_event


router = APIRouter(prefix="/api/admin", tags=["Administration"])


@router.get(
    "/users",
    response_model=AdminUserListResponse,
    summary="List user profiles",
    description="Lists all non-background user profiles for administrative correction.",
)
def users(admin=Depends(get_campus_admin), db: Session = Depends(get_db)):
    return {
        "users": db.scalars(
            select(User).where(User.role != "background").order_by(User.name)
        ).all()
    }


@router.put(
    "/users/{user_id}",
    response_model=UserResponse,
    summary="Correct a user profile",
    description="Allows an administrator to correct identity and academic profile fields.",
)
def update_user(
    user_id: int,
    payload: AdminUserUpdate,
    admin=Depends(get_campus_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user or user.role == "background":
        raise HTTPException(status_code=404, detail="User not found.")
    if user.id == admin.id:
        raise HTTPException(
            status_code=403,
            detail="Admins cannot edit their own profile or role.",
        )
    email = payload.email.strip().lower()
    id_number = payload.id_number.strip().upper()
    if not id_number:
        raise HTTPException(status_code=400, detail="ID number is required.")
    if "@" not in email:
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    if db.scalar(select(User.id).where(User.email == email, User.id != user_id)):
        raise HTTPException(status_code=409, detail="An account with that email already exists.")
    if db.scalar(select(User.id).where(User.id_number == id_number, User.id != user_id)):
        raise HTTPException(status_code=409, detail="That ID number is already registered.")
    user.name = payload.name.strip()
    user.email = email
    user.role = payload.role
    user.department = payload.department
    user.id_number = id_number
    user.year_of_study = payload.year_of_study
    user.designation = payload.designation
    user.admin_scope = payload.admin_scope
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="That email or ID number is already registered.")
    db.refresh(user)
    return user


@router.get(
    "/requests",
    response_model=PendingListResponse,
    summary="List pending approvals",
    description="Lists visible-user pending requests newest first and marks requests from the last hour.",
)
def pending_requests(admin=Depends(get_admin), db: Session = Depends(get_db)):
    expire_pending_requests(db)
    cutoff = datetime.utcnow() - timedelta(hours=1)
    query = (
        select(Request)
        .join(Request.user)
        .join(Request.resource)
        .where(Request.status == "pending", User.role != "background")
        .options(joinedload(Request.user), joinedload(Request.resource).joinedload(Resource.zone))
        .order_by(Request.created_at.desc(), Request.id.desc())
    )
    items = db.scalars(scope_resource_query(query, admin)).all()
    return {
        "requests": [
            request_response(item).model_dump() | {"is_new": item.created_at >= cutoff}
            for item in items
        ]
    }


@router.get(
    "/requests/{request_id}",
    response_model=AdminRequestDetailResponse,
    summary="Review a booking request",
    description="Returns requester and resource details with live slot and zone-load context.",
)
def request_detail(
    request_id: int,
    admin=Depends(get_admin),
    db: Session = Depends(get_db),
):
    expire_pending_requests(db)
    item = db.scalars(
        select(Request)
        .where(Request.id == request_id)
        .options(
            joinedload(Request.user),
            joinedload(Request.decider),
            joinedload(Request.resource).joinedload(Resource.zone),
        )
    ).first()
    if (
        not item
        or item.user.role == "background"
        or not admin_can_access_resource(admin, item.resource)
    ):
        raise HTTPException(status_code=404, detail="Request not found.")
    load = zone_loads(db, item.start, item.end).get(item.resource.zone_id, 0.0)
    return {
        "request": request_response(item),
        "slot_is_free": request_slot_is_free(db, item),
        "zone_load": load,
        "load_percent": round(load * 100),
    }


@router.post(
    "/requests/{request_id}/approve",
    response_model=BookingRequestResponse,
    summary="Approve a request",
    description="Approves one pending request while preserving its held booking slots.",
)
def approve_request(
    request_id: int,
    admin=Depends(get_admin),
    db: Session = Depends(get_db),
):
    expire_pending_requests(db)
    item = db.scalars(
        select(Request)
        .where(Request.id == request_id)
        .options(joinedload(Request.user), joinedload(Request.resource))
    ).first()
    if (
        not item
        or item.user.role == "background"
        or not admin_can_access_resource(admin, item.resource)
    ):
        raise HTTPException(status_code=404, detail="Request not found.")
    error = decide_request(db, booking_request=item, admin_id=admin.id, decision="approved")
    if error:
        raise HTTPException(status_code=409, detail=error)
    item = db.scalars(
        select(Request)
        .where(Request.id == request_id)
        .options(joinedload(Request.user), joinedload(Request.resource).joinedload(Resource.zone))
    ).first()
    return request_response(item)


@router.post(
    "/requests/{request_id}/reject",
    response_model=BookingRequestResponse,
    summary="Reject a request",
    description="Rejects one pending request and releases all held booking slots.",
)
def reject_request(
    request_id: int,
    payload: RejectRequest,
    admin=Depends(get_admin),
    db: Session = Depends(get_db),
):
    expire_pending_requests(db)
    item = db.scalars(
        select(Request)
        .where(Request.id == request_id)
        .options(joinedload(Request.user), joinedload(Request.resource))
    ).first()
    if (
        not item
        or item.user.role == "background"
        or not admin_can_access_resource(admin, item.resource)
    ):
        raise HTTPException(status_code=404, detail="Request not found.")
    error = decide_request(
        db,
        booking_request=item,
        admin_id=admin.id,
        decision="rejected",
        rejection_note=payload.rejection_note,
    )
    if error:
        raise HTTPException(status_code=409, detail=error)
    item = db.scalars(
        select(Request)
        .where(Request.id == request_id)
        .options(joinedload(Request.user), joinedload(Request.resource).joinedload(Resource.zone))
    ).first()
    return request_response(item)


@router.post(
    "/requests/{request_id}/extend",
    response_model=BookingRequestResponse,
    summary="Extend a booking request",
    description="Extends a pending or approved booking when the additional slots are available.",
)
def extend_request(
    request_id: int,
    payload: BookingExtension,
    admin=Depends(get_admin),
    db: Session = Depends(get_db),
):
    expire_pending_requests(db)
    item = db.scalars(
        select(Request)
        .where(Request.id == request_id)
        .options(joinedload(Request.user), joinedload(Request.resource))
    ).first()
    if (
        not item
        or item.user.role == "background"
        or not admin_can_access_resource(admin, item.resource)
    ):
        raise HTTPException(status_code=404, detail="Request not found.")
    error = extend_booking_request(
        db,
        booking_request=item,
        new_end=payload.new_end,
        admin_id=admin.id,
    )
    if error:
        raise HTTPException(status_code=409, detail=error)
    item = db.scalars(
        select(Request)
        .where(Request.id == request_id)
        .options(
            joinedload(Request.user),
            joinedload(Request.decider),
            joinedload(Request.resource).joinedload(Resource.zone),
        )
    ).first()
    return request_response(item)


@router.get(
    "/all-requests",
    response_model=AdminRequestListResponse,
    summary="List all visible-user requests",
    description="Lists requests newest first with status, role, and resource filters.",
)
def all_requests(
    status: str = "all",
    role: str = "all",
    resource_id: int | None = None,
    admin=Depends(get_admin),
    db: Session = Depends(get_db),
):
    expire_pending_requests(db)
    if status not in {"all", "pending", "approved", "rejected", "cancelled", "expired"}:
        raise HTTPException(status_code=400, detail="Invalid status filter.")
    if role not in {"all", "student", "faculty", "admin"}:
        raise HTTPException(status_code=400, detail="Invalid role filter.")
    query = (
        select(Request)
        .join(Request.user)
        .join(Request.resource)
        .where(User.role != "background")
        .options(joinedload(Request.user), joinedload(Request.resource).joinedload(Resource.zone))
        .order_by(Request.created_at.desc(), Request.id.desc())
    )
    if status != "all":
        query = query.where(Request.status == status)
    if role != "all":
        query = query.where(User.role == role)
    if resource_id is not None:
        query = query.where(Request.resource_id == resource_id)
    query = scope_resource_query(query, admin)
    return {
        "filters": {"status": status, "role": role, "resource_id": resource_id},
        "requests": [request_response(item) for item in db.scalars(query).all()],
    }


def history_query(
    admin,
    *,
    status: str = "all",
    date_from: date | None = None,
    date_to: date | None = None,
    resource_id: int | None = None,
    requester_id: int | None = None,
    deciding_admin_id: int | None = None,
    q: str = "",
):
    allowed = {"all", "pending", "approved", "rejected", "cancelled", "expired"}
    if status not in allowed:
        raise HTTPException(status_code=400, detail="Invalid status filter.")
    query = (
        select(Request)
        .join(Request.resource)
        .options(
            joinedload(Request.user),
            joinedload(Request.decider),
            joinedload(Request.resource).joinedload(Resource.zone),
        )
        .order_by(Request.created_at.desc(), Request.id.desc())
    )
    query = scope_resource_query(query, admin)
    if status != "all":
        query = query.where(Request.status == status)
    if date_from:
        local_start = datetime.combine(date_from, time.min)
        query = query.where(
            Request.created_at >= local_start - timedelta(hours=5, minutes=30)
        )
    if date_to:
        local_end = datetime.combine(date_to + timedelta(days=1), time.min)
        query = query.where(
            Request.created_at < local_end - timedelta(hours=5, minutes=30)
        )
    if resource_id is not None:
        query = query.where(Request.resource_id == resource_id)
    if requester_id is not None:
        query = query.where(Request.user_id == requester_id)
    if deciding_admin_id is not None:
        query = query.where(Request.decided_by == deciding_admin_id)
    text = q.strip()
    if text:
        pattern = f"%{text}%"
        query = query.where(
            or_(
                Request.purpose.ilike(pattern),
                Request.rejection_note.ilike(pattern),
                Request.status_reason.ilike(pattern),
                Request.user.has(User.name.ilike(pattern)),
                Request.resource.has(Resource.name.ilike(pattern)),
                Request.events.any(RequestEvent.note.ilike(pattern)),
            )
        )
    return query


@router.get(
    "/history",
    response_model=AdminHistoryResponse,
    summary="Search scoped request history",
    description="Filters the complete request audit history within the administrator's resource scope.",
)
def request_history(
    status: str = "all",
    date_from: date | None = None,
    date_to: date | None = None,
    resource_id: int | None = None,
    requester_id: int | None = None,
    deciding_admin_id: int | None = None,
    q: str = "",
    admin=Depends(get_admin),
    db: Session = Depends(get_db),
):
    expire_pending_requests(db)
    query = history_query(
        admin,
        status=status,
        date_from=date_from,
        date_to=date_to,
        resource_id=resource_id,
        requester_id=requester_id,
        deciding_admin_id=deciding_admin_id,
        q=q,
    )
    resources_query = select(Resource).options(joinedload(Resource.zone)).order_by(Resource.name)
    resources = db.scalars(scope_resource_query(resources_query, admin)).all()
    requesters = db.scalars(
        select(User)
        .join(Request, Request.user_id == User.id)
        .join(Resource, Request.resource_id == Resource.id)
        .where(Resource.type.in_([item.type for item in resources]))
        .distinct()
        .order_by(User.name)
    ).all()
    deciding_admins = db.scalars(
        select(User).where(User.role == "admin").order_by(User.name)
    ).all()
    return {
        "filters": {
            "status": status,
            "date_from": date_from,
            "date_to": date_to,
            "resource_id": resource_id,
            "requester_id": requester_id,
            "deciding_admin_id": deciding_admin_id,
            "q": q.strip(),
        },
        "requests": [request_response(item) for item in db.scalars(query).unique().all()],
        "resources": [resource_response(item) for item in resources],
        "requesters": requesters,
        "deciding_admins": deciding_admins,
    }


@router.get(
    "/history.csv",
    summary="Export scoped request history",
    description="Downloads the currently filtered, scope-limited request history as CSV.",
)
def export_request_history(
    status: str = "all",
    date_from: date | None = None,
    date_to: date | None = None,
    resource_id: int | None = None,
    requester_id: int | None = None,
    deciding_admin_id: int | None = None,
    q: str = "",
    admin=Depends(get_admin),
    db: Session = Depends(get_db),
):
    expire_pending_requests(db)
    items = db.scalars(
        history_query(
            admin,
            status=status,
            date_from=date_from,
            date_to=date_to,
            resource_id=resource_id,
            requester_id=requester_id,
            deciding_admin_id=deciding_admin_id,
            q=q,
        )
    ).unique().all()
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        ["Request", "Status", "Requester", "Resource", "Start", "End", "Purpose", "Deciding admin", "Decision note"]
    )
    for item in items:
        writer.writerow(
            [
                item.id,
                item.status.upper(),
                item.user.name,
                item.resource.name,
                item.start.isoformat(sep=" "),
                item.end.isoformat(sep=" "),
                item.purpose,
                item.decider.name if item.decider else "",
                item.rejection_note or item.status_reason or "",
            ]
        )
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=quorum-request-history.csv"},
    )


@router.get(
    "/request-resources",
    response_model=list[ResourceResponse],
    summary="List resources in my approval scope",
    description="Returns resources whose requests the signed-in administrator may review.",
)
def request_resources(admin=Depends(get_admin), db: Session = Depends(get_db)):
    query = select(Resource).options(joinedload(Resource.zone)).order_by(Resource.name)
    return [resource_response(item) for item in db.scalars(scope_resource_query(query, admin)).all()]


@router.get(
    "/resources",
    response_model=AdminResourcesResponse,
    summary="List managed resources",
    description="Returns all resources and zones for the administration screen.",
)
def admin_resources(admin=Depends(get_campus_admin), db: Session = Depends(get_db)):
    resources = db.scalars(
        select(Resource).options(joinedload(Resource.zone)).order_by(Resource.name)
    ).all()
    zones = db.scalars(select(Zone).order_by(Zone.name)).all()
    return {"resources": resources, "zones": zones}


@router.post(
    "/resources",
    response_model=ResourceResponse,
    status_code=201,
    summary="Create a resource",
    description="Registers a new active campus resource.",
)
def create_resource(
    payload: ResourceCreate,
    admin=Depends(get_campus_admin),
    db: Session = Depends(get_db),
):
    if not db.get(Zone, payload.zone_id):
        raise HTTPException(status_code=400, detail="Zone not found.")
    resource = Resource(**payload.model_dump(), status="active")
    db.add(resource)
    db.commit()
    resource = db.scalars(
        select(Resource).where(Resource.id == resource.id).options(joinedload(Resource.zone))
    ).first()
    return resource_response(resource)


@router.put(
    "/resources/{resource_id}",
    response_model=ResourceResponse,
    summary="Update a resource",
    description="Updates resource details, operating hours, approval policy, and status.",
)
def update_resource(
    resource_id: int,
    payload: ResourceUpdate,
    admin=Depends(get_campus_admin),
    db: Session = Depends(get_db),
):
    resource = db.get(Resource, resource_id)
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found.")
    if not db.get(Zone, payload.zone_id):
        raise HTTPException(status_code=400, detail="Zone not found.")
    current_status = resource.status
    for field, value in payload.model_dump().items():
        if field == "status" and current_status == "on_hold":
            continue
        setattr(resource, field, value)
    db.commit()
    resource = db.scalars(
        select(Resource).where(Resource.id == resource_id).options(joinedload(Resource.zone))
    ).first()
    return resource_response(resource)


@router.post(
    "/resources/{resource_id}/hold",
    response_model=ResourceResponse,
    summary="Put a resource on hold",
    description="Previews then cancels pending and future approved bookings before placing a resource on hold.",
)
def hold_resource(
    resource_id: int,
    payload: ResourceHoldCreate,
    admin=Depends(get_campus_admin),
    db: Session = Depends(get_db),
):
    expire_pending_requests(db)
    resource = db.get(Resource, resource_id)
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found.")
    reason = payload.reason.strip()
    if not reason:
        raise HTTPException(status_code=400, detail="Hold reason is required.")
    now = india_now()
    affected = db.scalars(
        select(Request)
        .where(
            Request.resource_id == resource_id,
            or_(
                Request.status == "pending",
                (Request.status == "approved") & (Request.start > now),
            ),
        )
        .options(joinedload(Request.user), joinedload(Request.resource).joinedload(Resource.zone))
        .order_by(Request.start, Request.id)
    ).all()
    affected_ids = sorted(item.id for item in affected)
    if affected_ids and sorted(payload.confirmed_request_ids or []) != affected_ids:
        raise HTTPException(
            status_code=409,
            detail={
                "title": "Bookings will be cancelled",
                "reason": f"{len(affected)} booking(s) will be cancelled by this hold.",
                "affected_requests": [
                    request_response(item).model_dump(mode="json") for item in affected
                ],
            },
        )
    cancellation_reason = f"Resource on hold: {reason}"
    for item in affected:
        item.status = "cancelled"
        item.status_reason = cancellation_reason
        add_request_event(
            db,
            request_id=item.id,
            event="auto_cancelled_hold",
            actor_user_id=admin.id,
            note=cancellation_reason,
        )
    if affected_ids:
        db.execute(delete(BookingSlot).where(BookingSlot.request_id.in_(affected_ids)))
    resource.status = "on_hold"
    resource.hold_reason = reason
    resource.expected_back = payload.expected_back
    db.commit()
    resource = db.scalars(
        select(Resource).where(Resource.id == resource_id).options(joinedload(Resource.zone))
    ).first()
    return resource_response(resource)


@router.post(
    "/resources/{resource_id}/lift-hold",
    response_model=ResourceResponse,
    summary="Lift a resource hold",
    description="Returns an on-hold resource to active service.",
)
def lift_resource_hold(
    resource_id: int,
    admin=Depends(get_campus_admin),
    db: Session = Depends(get_db),
):
    resource = db.get(Resource, resource_id)
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found.")
    if resource.status != "on_hold":
        raise HTTPException(status_code=409, detail="Resource is not on hold.")
    resource.status = "active"
    resource.hold_reason = None
    resource.expected_back = None
    db.commit()
    resource = db.scalars(
        select(Resource).where(Resource.id == resource_id).options(joinedload(Resource.zone))
    ).first()
    return resource_response(resource)


@router.post(
    "/resources/{resource_id}/unavailability",
    response_model=ResourceResponse,
    summary="Block a resource window",
    description="Adds a maintenance or closure window to a resource.",
)
def create_unavailability(
    resource_id: int,
    payload: UnavailabilityCreate,
    admin=Depends(get_campus_admin),
    db: Session = Depends(get_db),
):
    expire_pending_requests(db)
    resource = db.get(Resource, resource_id)
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found.")
    error = validate_request_window(resource, payload.start, payload.end)
    if error and "active" not in error:
        raise HTTPException(status_code=400, detail=error)
    affected = db.scalars(
        select(Request)
        .where(
            Request.resource_id == resource_id,
            Request.status.in_(("pending", "approved")),
            Request.start < payload.end,
            Request.end > payload.start,
        )
        .options(joinedload(Request.user), joinedload(Request.resource).joinedload(Resource.zone))
        .order_by(Request.start, Request.id)
    ).all()
    affected_ids = sorted(item.id for item in affected)
    confirmed_ids = sorted(payload.confirmed_request_ids or [])
    if affected_ids and confirmed_ids != affected_ids:
        raise HTTPException(
            status_code=409,
            detail={
                "title": "Bookings will be cancelled",
                "reason": f"{len(affected)} booking(s) overlap this window.",
                "affected_requests": [
                    request_response(item).model_dump(mode="json") for item in affected
                ],
            },
        )
    reason = payload.reason.strip()
    if not reason:
        raise HTTPException(status_code=400, detail="Reason is required.")
    for item in affected:
        item.status = "cancelled"
        item.status_reason = f"Resource unavailable: {reason}"
        add_request_event(
            db,
            request_id=item.id,
            event="auto_cancelled_unavailability",
            actor_user_id=admin.id,
            note=item.status_reason,
        )
    if affected_ids:
        db.execute(delete(BookingSlot).where(BookingSlot.request_id.in_(affected_ids)))
    db.add(
        Unavailability(
            resource_id=resource_id,
            start=payload.start,
            end=payload.end,
            reason=reason,
        )
    )
    db.commit()
    resource = db.scalars(
        select(Resource).where(Resource.id == resource_id).options(joinedload(Resource.zone))
    ).first()
    return resource_response(resource)
