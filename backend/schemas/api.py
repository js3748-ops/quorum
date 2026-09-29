from datetime import datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class MessageResponse(BaseModel):
    message: str


class UserResponse(ORMModel):
    id: int
    name: str
    email: str
    role: Literal["admin", "faculty", "student"]


class AuthResponse(BaseModel):
    user: UserResponse


class LoginRequest(BaseModel):
    email: str
    password: str


class DemoLoginRequest(BaseModel):
    email: str


class SignupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str
    password: str = Field(min_length=8)
    role: Literal["faculty", "student"]


class ZoneResponse(ORMModel):
    id: int
    name: str
    building: str
    floor: str


class ResourceResponse(ORMModel):
    id: int
    name: str
    type: str
    zone_id: int
    zone: ZoneResponse
    capacity: int
    equipment: list[str]
    requires_approval: bool
    status: str
    open_time: time
    close_time: time


class UnavailabilityResponse(ORMModel):
    id: int
    start: datetime
    end: datetime
    reason: str


class RequestUserResponse(ORMModel):
    id: int
    name: str
    role: str
    email: str | None = None


class BookingRequestResponse(ORMModel):
    id: int
    user_id: int
    user: RequestUserResponse
    resource_id: int
    resource: ResourceResponse
    start: datetime
    end: datetime
    attendees: int
    purpose: str
    status: str
    decided_by: int | None
    decided_at: datetime | None
    rejection_note: str | None
    created_at: datetime
    auto_approval_label: str | None = None


class BookingCreate(BaseModel):
    resource_id: int
    start: datetime
    end: datetime
    attendees: int = Field(ge=1)
    purpose: str = ""


class AlternativeResponse(BaseModel):
    kind: str
    resource: ResourceResponse
    start: datetime
    end: datetime


class ConflictResponse(BaseModel):
    title: str
    reason: str
    alternatives: list[AlternativeResponse]


class SearchFilters(BaseModel):
    type: str
    attendees: int
    equipment: list[str]
    start: datetime
    end: datetime
    query: str = ""


class RankedResourceResponse(BaseModel):
    resource: ResourceResponse
    zone_load: float
    load_percent: int
    bar_width: int
    reason: str
    approval_message: str


class SearchResponse(BaseModel):
    filters: SearchFilters
    results: list[RankedResourceResponse]


class ResourceDetailResponse(BaseModel):
    resource: ResourceResponse
    unavailability: list[UnavailabilityResponse]
    recent_requests: list[BookingRequestResponse]
    approval_message: str


class RequestListResponse(BaseModel):
    requests: list[BookingRequestResponse]


class PendingRequestResponse(BookingRequestResponse):
    is_new: bool


class PendingListResponse(BaseModel):
    requests: list[PendingRequestResponse]


class RejectRequest(BaseModel):
    rejection_note: str = ""


class AdminRequestFilters(BaseModel):
    status: str
    role: str
    resource_id: int | None


class AdminRequestListResponse(BaseModel):
    filters: AdminRequestFilters
    requests: list[BookingRequestResponse]


class ResourceCreate(BaseModel):
    name: str
    type: str
    zone_id: int
    capacity: int = Field(ge=1)
    equipment: list[str] = []
    requires_approval: bool = False
    open_time: time
    close_time: time


class ResourceUpdate(ResourceCreate):
    status: Literal["active", "maintenance"]


class UnavailabilityCreate(BaseModel):
    start: datetime
    end: datetime
    reason: str


class AdminResourcesResponse(BaseModel):
    resources: list[ResourceResponse]
    zones: list[ZoneResponse]


class DashboardMetric(BaseModel):
    resource: ResourceResponse
    booked_hours: float
    open_hours: float
    utilization: float
    percent: int


class ZoneMetric(BaseModel):
    zone: ZoneResponse
    booked_hours: float
    open_hours: float
    utilization: float
    percent: int


class PeakCell(BaseModel):
    percent: int
    intensity: str
    booked_count: int
    label: str


class PeakRow(BaseModel):
    day: str
    cells: list[PeakCell]


class UsageExtreme(BaseModel):
    resource: ResourceResponse
    booked_hours: float


class DashboardResponse(BaseModel):
    week_start: datetime
    week_last_day: datetime
    counts: dict[str, int]
    resource_rows: list[DashboardMetric]
    zone_rows: list[ZoneMetric]
    peak_rows: list[PeakRow]
    slot_labels: list[str]
    most_used: UsageExtreme | None
    least_used: UsageExtreme | None
