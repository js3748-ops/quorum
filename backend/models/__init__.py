from datetime import datetime, time, timedelta, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from backend.database import Base


INDIA_TIMEZONE = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")


def india_now() -> datetime:
    return datetime.now(INDIA_TIMEZONE).replace(tzinfo=None)


class Zone(Base):
    __tablename__ = "zones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    building: Mapped[str] = mapped_column(String(120), nullable=False)
    floor: Mapped[str] = mapped_column(String(40), nullable=False)

    resources: Mapped[list["Resource"]] = relationship(back_populates="zone")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    password_salt: Mapped[str | None] = mapped_column(String(32), nullable=True)
    role: Mapped[str] = mapped_column(String(30), nullable=False, default="student")
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    department: Mapped[str | None] = mapped_column(String(40), nullable=True)
    id_number: Mapped[str | None] = mapped_column(String(80), nullable=True, unique=True)
    year_of_study: Mapped[int | None] = mapped_column(Integer, nullable=True)
    designation: Mapped[str | None] = mapped_column(String(120), nullable=True)
    admin_scope: Mapped[str | None] = mapped_column(String(30), nullable=True)
    member_since: Mapped[datetime] = mapped_column(DateTime, default=india_now, nullable=False)


class Resource(Base):
    __tablename__ = "resources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id"), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    equipment: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    open_time: Mapped[time] = mapped_column(Time, nullable=False)
    close_time: Mapped[time] = mapped_column(Time, nullable=False)

    zone: Mapped[Zone] = relationship(back_populates="resources")
    unavailability: Mapped[list["Unavailability"]] = relationship(
        back_populates="resource", cascade="all, delete-orphan"
    )
    requests: Mapped[list["Request"]] = relationship(back_populates="resource")


class Unavailability(Base):
    __tablename__ = "unavailability"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id"), nullable=False)
    start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    reason: Mapped[str] = mapped_column(String(80), nullable=False)

    resource: Mapped[Resource] = relationship(back_populates="unavailability")


class Request(Base):
    __tablename__ = "requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id"), nullable=False)
    start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    attendees: Mapped[int] = mapped_column(Integer, nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rejection_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime, default=india_now, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    user: Mapped[User] = relationship(foreign_keys=[user_id])
    decider: Mapped[User | None] = relationship(foreign_keys=[decided_by])
    resource: Mapped[Resource] = relationship(back_populates="requests")
    slots: Mapped[list["BookingSlot"]] = relationship(
        back_populates="request", cascade="all, delete-orphan"
    )


class BookingSlot(Base):
    __tablename__ = "booking_slots"
    __table_args__ = (UniqueConstraint("resource_id", "slot_start", name="uq_resource_slot"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("requests.id"), nullable=False)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id"), nullable=False)
    slot_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    request: Mapped[Request] = relationship(back_populates="slots")
    resource: Mapped[Resource] = relationship()
