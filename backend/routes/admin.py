from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from backend.database import get_db
from backend.models import BookingSlot, Request, Resource, Unavailability, User, Zone
from backend.routes.dependencies import get_admin, get_campus_admin
from backend.routes.helpers import request_response, resource_response
from backend.schemas import (
    AdminRequestListResponse,
    AdminRequestDetailResponse,
    AdminResourcesResponse,
    AdminUserListResponse,
    AdminUserUpdate,
    BookingRequestResponse,
    PendingListResponse,
    RejectRequest,
    ResourceCreate,
    ResourceResponse,
    ResourceUpdate,
    UnavailabilityCreate,
    UserResponse,
)
from backend.services.analytics import zone_loads
from backend.services.admin_scope import admin_can_access_resource, scope_resource_query
from backend.services.booking import (
    decide_request,
    expire_pending_requests,
    request_slot_is_free,
    validate_request_window,
)


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
    for field, value in payload.model_dump().items():
        setattr(resource, field, value)
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
