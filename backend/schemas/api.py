from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Department = Literal["CSE", "ECE", "EEE", "Mechanical", "Civil", "Biotech", "Other"]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class MessageResponse(BaseModel):
    message: str


class UserResponse(ORMModel):
    id: int
    name: str
    email: str
    role: Literal["admin", "faculty", "student"]
    department: Department
    id_number: str
    year_of_study: int | None
    designation: str | None
    admin_scope: str | None
    member_since: datetime


class AuthResponse(BaseModel):
    user: UserResponse


class LoginRequest(BaseModel):
    email: str
    password: str


class AuthChallengeResponse(BaseModel):
    challenge_id: str
    message: str
    expires_in_seconds: int


class OtpVerifyRequest(BaseModel):
    challenge_id: str = Field(min_length=20, max_length=64)
    otp: str = Field(pattern=r"^\d{6}$")


class DemoLoginRequest(BaseModel):
    email: str


class SignupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str
    password: str = Field(min_length=8)
    role: Literal["faculty", "student"]
    department: Department
    id_number: str = Field(min_length=1, max_length=80)
    year_of_study: int | None = Field(default=None, ge=1, le=4)

    @model_validator(mode="after")
    def validate_role_fields(self):
        if self.role == "student" and self.year_of_study is None:
            raise ValueError("Year of study is required for students.")
        if self.role == "faculty":
            self.year_of_study = None
        return self


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
    hold_reason: str | None
    expected_back: date | None
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
    department: str | None = None
    id_number: str | None = None
    year_of_study: int | None = None
    designation: str | None = None
    admin_scope: str | None = None
    member_since: datetime | None = None


class RequestEventResponse(ORMModel):
    id: int
    event: str
    actor_user_id: int | None
    actor: RequestUserResponse | None
    note: str | None
    created_at: datetime


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
    decider: RequestUserResponse | None
    decided_at: datetime | None
    rejection_note: str | None
    status_reason: str | None
    confirmed_at: datetime | None
    created_at: datetime
    events: list[RequestEventResponse] = Field(default_factory=list)


class BookingCreate(BaseModel):
    resource_id: int
    start: datetime
    end: datetime
    attendees: int = Field(ge=1)
    purpose: str = Field(min_length=15)
    confirmed: Literal[True]

    @model_validator(mode="after")
    def validate_purpose(self):
        self.purpose = self.purpose.strip()
        if len(self.purpose) < 15:
            raise ValueError("Purpose must be at least 15 characters.")
        return self


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
    show_on_hold: bool = False


class RankedResourceResponse(BaseModel):
    resource: ResourceResponse
    zone_load: float
    load_percent: int
    bar_width: int
    reason: str
    approval_message: str
    available: bool
    availability_label: str | None = None


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


class BookingExtension(BaseModel):
    new_end: datetime


class AdminRequestFilters(BaseModel):
    status: str
    role: str
    resource_id: int | None


class AdminRequestListResponse(BaseModel):
    filters: AdminRequestFilters
    requests: list[BookingRequestResponse]


class AdminRequestDetailResponse(BaseModel):
    request: BookingRequestResponse
    slot_is_free: bool
    zone_load: float
    load_percent: int


class AdminUserListResponse(BaseModel):
    users: list[UserResponse]


class AdminUserUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str
    role: Literal["admin", "faculty", "student"]
    department: Department
    id_number: str = Field(min_length=1, max_length=80)
    year_of_study: int | None = Field(default=None, ge=1, le=4)
    designation: str | None = Field(default=None, max_length=120)
    admin_scope: Literal["all", "labs", "facilities"] | None = None

    @model_validator(mode="after")
    def validate_role_fields(self):
        if self.role == "student" and self.year_of_study is None:
            raise ValueError("Year of study is required for students.")
        if self.role != "student":
            self.year_of_study = None
        if self.role == "admin":
            if not (self.designation or "").strip() or self.admin_scope is None:
                raise ValueError("Designation and admin scope are required for admins.")
            self.designation = self.designation.strip()
        else:
            self.designation = None
            self.admin_scope = None
        return self


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
    status: Literal["active", "inactive"]


class ResourceHoldCreate(BaseModel):
    reason: str = Field(min_length=1, max_length=240)
    expected_back: date | None = None
    confirmed_request_ids: list[int] | None = None


class UnavailabilityCreate(BaseModel):
    start: datetime
    end: datetime
    reason: str
    confirmed_request_ids: list[int] | None = None


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


class ZoneLoadResponse(BaseModel):
    zone: ZoneResponse
    load: float
    percent: int


class UserDashboardResponse(BaseModel):
    upcoming: list[BookingRequestResponse]
    pending: list[BookingRequestResponse]
    recent_decisions: list[BookingRequestResponse]
    quieter_zones: list[ZoneLoadResponse]
    holds: list[ResourceResponse]


class AdminHomeResponse(BaseModel):
    pending: list[PendingRequestResponse]
    today_counts: dict[str, int]
    holds: list[ResourceResponse]


class HistoryFilters(BaseModel):
    status: str
    date_from: date | None
    date_to: date | None
    resource_id: int | None
    requester_id: int | None
    deciding_admin_id: int | None
    q: str


class AdminHistoryResponse(BaseModel):
    filters: HistoryFilters
    requests: list[BookingRequestResponse]
    resources: list[ResourceResponse]
    requesters: list[RequestUserResponse]
    deciding_admins: list[RequestUserResponse]


class SensorCreate(BaseModel):
    resource_id: int
    name: str = Field(min_length=1, max_length=120)
    is_simulated: bool = False

    @model_validator(mode="after")
    def validate_name(self):
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("Sensor name is required.")
        return self


class SensorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    is_active: bool | None = None

    @model_validator(mode="after")
    def validate_fields(self):
        if self.name is None and self.is_active is None:
            raise ValueError("Provide a new name or an active state.")
        if self.name is not None:
            self.name = self.name.strip()
            if not self.name:
                raise ValueError("Sensor name is required.")
        return self


class SensorResponse(BaseModel):
    id: int
    resource_id: int
    resource_name: str
    name: str
    is_active: bool
    is_simulated: bool
    status: Literal["online", "offline", "inactive"]
    last_seen_at: datetime | None
    created_at: datetime


class SensorListResponse(BaseModel):
    sensors: list[SensorResponse]


class SensorKeyResponse(BaseModel):
    sensor: SensorResponse
    api_key: str
    message: str


class OccupancyReadingCreate(BaseModel):
    # Counts and timestamps only. Unknown fields (for example image data) are rejected.
    model_config = ConfigDict(extra="forbid")

    people_count: int = Field(ge=0, le=1000, strict=True)
    recorded_at: datetime | None = None


class OccupancyReadingResponse(BaseModel):
    id: int
    sensor_id: int
    resource_id: int
    people_count: int
    recorded_at: datetime


class CurrentBookingResponse(BaseModel):
    request_id: int
    start: datetime
    end: datetime
    expected_attendance: int


class LiveOccupancyItem(BaseModel):
    resource: ResourceResponse
    current_booking: CurrentBookingResponse | None
    people_count: int | None
    capacity: int
    sensor_status: Literal["online", "offline", "unsensored"]
    last_reading_at: datetime | None
    status: str


class LiveOccupancyResponse(BaseModel):
    generated_at: datetime
    resources: list[LiveOccupancyItem]


class OccupancyBucket(BaseModel):
    minute: datetime
    average_people_count: float
    median_people_count: int
    min_people_count: int
    max_people_count: int
    readings: int


class OccupancyHistoryResponse(BaseModel):
    resource_id: int
    start: datetime
    end: datetime
    buckets: list[OccupancyBucket]
