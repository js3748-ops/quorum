from datetime import datetime, timedelta, timezone


INDIA_TIMEZONE = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")


def india_now() -> datetime:
    return datetime.now(INDIA_TIMEZONE).replace(tzinfo=None)
