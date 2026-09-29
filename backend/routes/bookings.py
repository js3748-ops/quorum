from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from backend.database import get_db
from backend.models import Request, Resource
from backend.routes.dependencies import get_current_user
from backend.routes.helpers import request_response, resource_response
from backend.schemas import BookingCreate, BookingRequestResponse, RequestListResponse
from backend.services.booking import create_booking_request, suggest_alternatives


router = APIRouter(prefix="/api", tags=["Bookings"])


@router.post(
    "/requests",
    response_model=BookingRequestResponse,
    status_code=201,
    summary="Create a booking request",
    description="Creates a held request or returns a conflict with nearby alternatives.",
)
def create_request(
    payload: BookingCreate,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    resource = db.scalars(
        select(Resource)
        .where(Resource.id == payload.resource_id)
        .options(joinedload(Resource.zone))
    ).first()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found.")
    created, conflict = create_booking_request(
        db,
        user_id=user.id,
        user_role=user.role,
        resource=resource,
        start=payload.start,
        end=payload.end,
        attendees=payload.attendees,
        purpose=payload.purpose,
    )
    if conflict:
        outside_hours = (
            payload.start.date() != payload.end.date()
            or payload.start.time() < resource.open_time
            or payload.end.time() > resource.close_time
        )
        alternatives = suggest_alternatives(
            db, resource, payload.start, payload.end, payload.attendees
        )
        detail = {
            "title": "Outside open hours" if outside_hours else "Conflict",
            "reason": conflict,
            "alternatives": [
                {
                    "kind": item["kind"],
                    "resource": resource_response(item["resource"]).model_dump(mode="json"),
                    "start": item["start"].isoformat(),
                    "end": item["end"].isoformat(),
                }
                for item in alternatives
            ],
        }
        raise HTTPException(status_code=409, detail=detail)
    created = db.scalars(
        select(Request)
        .where(Request.id == created.id)
        .options(joinedload(Request.user), joinedload(Request.resource).joinedload(Resource.zone))
    ).first()
    return request_response(created)


@router.get(
    "/requests/{request_id}",
    response_model=BookingRequestResponse,
    summary="Get a booking request",
    description="Returns a request to its owner or an administrator.",
)
def get_request(
    request_id: int,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = db.scalars(
        select(Request)
        .where(Request.id == request_id)
        .options(joinedload(Request.user), joinedload(Request.resource).joinedload(Resource.zone))
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Request not found.")
    if item.user_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="This request belongs to another user.")
    return request_response(item)


@router.get(
    "/my-requests",
    response_model=RequestListResponse,
    summary="List my requests",
    description="Lists the signed-in user's requests newest first with an optional status filter.",
)
def my_requests(
    status: str = "all",
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    allowed = {"all", "pending", "approved", "rejected", "cancelled"}
    if status not in allowed:
        raise HTTPException(status_code=400, detail="Invalid status filter.")
    query = (
        select(Request)
        .where(Request.user_id == user.id)
        .options(joinedload(Request.user), joinedload(Request.resource).joinedload(Resource.zone))
        .order_by(Request.created_at.desc(), Request.id.desc())
    )
    if status != "all":
        query = query.where(Request.status == status)
    return {"requests": [request_response(item) for item in db.scalars(query).all()]}
