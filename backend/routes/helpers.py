from backend.models import Request, Resource, User
from backend.schemas import BookingRequestResponse, ResourceResponse


def approval_message(user: User, resource: Resource) -> str:
    if user.role == "student" or (user.role == "faculty" and resource.requires_approval):
        return "This request will need admin approval."
    return "This will be approved immediately."


def request_response(item: Request) -> BookingRequestResponse:
    label = None
    if item.status == "approved" and item.user.role == "faculty" and not item.decided_by:
        label = "Auto-approved (faculty)"
    response = BookingRequestResponse.model_validate(item)
    return response.model_copy(update={"auto_approval_label": label})


def resource_response(resource: Resource) -> ResourceResponse:
    return ResourceResponse.model_validate(resource)
