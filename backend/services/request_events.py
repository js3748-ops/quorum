from datetime import datetime

from sqlalchemy.orm import Session

from backend.models import RequestEvent
from backend.services.booking_time import india_now


def add_request_event(
    db: Session,
    *,
    request_id: int,
    event: str,
    actor_user_id: int | None = None,
    note: str | None = None,
    created_at: datetime | None = None,
) -> RequestEvent:
    item = RequestEvent(
        request_id=request_id,
        event=event,
        actor_user_id=actor_user_id,
        note=(note or "").strip() or None,
        created_at=created_at or india_now(),
    )
    db.add(item)
    return item
