from datetime import timedelta, timezone

from backend.models import Request, Resource, User
from backend.schemas import BookingRequestResponse, ResourceResponse


INDIA_TIMEZONE = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")


def approval_message(user: User, resource: Resource) -> str:
    return "This request will need admin approval."


def request_response(item: Request) -> BookingRequestResponse:
    response = BookingRequestResponse.model_validate(item)
    created_at = item.created_at.replace(tzinfo=timezone.utc)
    decided_at = (
        item.decided_at.replace(tzinfo=INDIA_TIMEZONE) if item.decided_at else None
    )
    return response.model_copy(
        update={"created_at": created_at, "decided_at": decided_at}
    )


def resource_response(resource: Resource) -> ResourceResponse:
    return ResourceResponse.model_validate(resource)
