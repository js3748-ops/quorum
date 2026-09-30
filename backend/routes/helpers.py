from datetime import timedelta, timezone

from backend.models import Request, Resource, User
from backend.schemas import BookingRequestResponse, ResourceResponse


INDIA_TIMEZONE = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")


def approval_message(user: User, resource: Resource) -> str:
    return "This request will need admin approval."


def request_response(item: Request) -> BookingRequestResponse:
    response = BookingRequestResponse.model_validate(item)
    created_at = item.created_at.replace(tzinfo=timezone.utc)
    confirmed_at = (
        item.confirmed_at.replace(tzinfo=INDIA_TIMEZONE)
        if item.confirmed_at
        else None
    )
    decided_at = (
        item.decided_at.replace(tzinfo=INDIA_TIMEZONE) if item.decided_at else None
    )
    return response.model_copy(
        update={
            "created_at": created_at,
            "confirmed_at": confirmed_at,
            "decided_at": decided_at,
            "purpose": (item.purpose or "").strip() or "No purpose given",
        }
    )


def resource_response(resource: Resource) -> ResourceResponse:
    return ResourceResponse.model_validate(resource)
