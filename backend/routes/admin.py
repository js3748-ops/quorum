from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from backend.database import get_db
from backend.models import Request, Resource, Unavailability, User, Zone
from backend.routes.dependencies import get_admin
from backend.routes.helpers import request_response, resource_response
from backend.schemas import (
    AdminRequestListResponse,
    AdminResourcesResponse,
    BookingRequestResponse,
    PendingListResponse,
    RejectRequest,
    ResourceCreate,
    ResourceResponse,
    ResourceUpdate,
    UnavailabilityCreate,
)
from backend.services.booking import decide_request, validate_request_window


router = APIRouter(prefix="/api/admin", tags=["Administration"])


@router.get(
    "/requests",
    response_model=PendingListResponse,
    summary="List pending approvals",
    description="Lists visible-user pending requests newest first and marks requests from the last hour.",
)
def pending_requests(admin=Depends(get_admin), db: Session = Depends(get_db)):
    cutoff = datetime.utcnow() - timedelta(hours=1)
    items = db.scalars(
        select(Request)
        .join(Request.user)
        .where(Request.status == "pending", User.role != "background")
        .options(joinedload(Request.user), joinedload(Request.resource).joinedload(Resource.zone))
        .order_by(Request.created_at.desc(), Request.id.desc())
    ).all()
    return {
        "requests": [
            request_response(item).model_dump() | {"is_new": item.created_at >= cutoff}
            for item in items
        ]
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
    item = db.get(Request, request_id)
    if not item:
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
    item = db.get(Request, request_id)
    if not item:
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
    if status not in {"all", "pending", "approved", "rejected", "cancelled"}:
        raise HTTPException(status_code=400, detail="Invalid status filter.")
    if role not in {"all", "student", "faculty", "admin"}:
        raise HTTPException(status_code=400, detail="Invalid role filter.")
    query = (
        select(Request)
        .join(Request.user)
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
    return {
        "filters": {"status": status, "role": role, "resource_id": resource_id},
        "requests": [request_response(item) for item in db.scalars(query).all()],
    }


@router.get(
    "/resources",
    response_model=AdminResourcesResponse,
    summary="List managed resources",
    description="Returns all resources and zones for the administration screen.",
)
def admin_resources(admin=Depends(get_admin), db: Session = Depends(get_db)):
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
    admin=Depends(get_admin),
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
    admin=Depends(get_admin),
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
    admin=Depends(get_admin),
    db: Session = Depends(get_db),
):
    resource = db.get(Resource, resource_id)
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found.")
    error = validate_request_window(resource, payload.start, payload.end)
    if error and "active" not in error:
        raise HTTPException(status_code=400, detail=error)
    db.add(Unavailability(resource_id=resource_id, **payload.model_dump()))
    db.commit()
    resource = db.scalars(
        select(Resource).where(Resource.id == resource_id).options(joinedload(Resource.zone))
    ).first()
    return resource_response(resource)
