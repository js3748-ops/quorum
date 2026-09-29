from backend.models import Request, Resource, User
from backend.schemas import BookingRequestResponse, ResourceResponse


def approval_message(user: User, resource: Resource) -> str:
    return "This request will need admin approval."


def request_response(item: Request) -> BookingRequestResponse:
    return BookingRequestResponse.model_validate(item)


def resource_response(resource: Resource) -> ResourceResponse:
    return ResourceResponse.model_validate(resource)
