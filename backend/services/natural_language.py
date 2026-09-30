import json
import os
import re
from datetime import date, datetime, time, timedelta
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


RESOURCE_TYPES = {
    "lab": "lab",
    "laboratory": "lab",
    "classroom": "classroom",
    "class room": "classroom",
    "room": "classroom",
    "seminar hall": "seminar_hall",
    "seminar room": "seminar_hall",
    "hall": "seminar_hall",
    "equipment": "equipment",
}
EQUIPMENT_KEYWORDS = {
    "projector": "projector",
    "linux": "linux",
    "gpu": "gpu",
    "whiteboard": "whiteboard",
    "microphone": "mic",
    "mic": "mic",
    "video": "video",
    "camera": "camera",
    "tripod": "tripod",
    "stage": "stage",
    "mac": "mac",
    "display": "display",
    "scanner": "scanner",
    "speaker": "speaker",
    "fume hood": "fume_hood",
    "oscilloscope": "oscilloscope",
    "sensors": "sensors",
    "sensor": "sensors",
    "tools": "tools",
}
WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


class VagueSearchError(ValueError):
    pass


def parse_natural_language(text: str, now: datetime | None = None) -> dict[str, object]:
    now = now or datetime.now()
    api_key = os.getenv("LLM_API_KEY")
    if api_key:
        try:
            extracted = _parse_with_llm(text, now, api_key)
            actionable = extracted.get("actionable", True)
            if actionable is False or str(actionable).strip().lower() == "false":
                clarification = str(extracted.get("clarification", "")).strip()
                raise VagueSearchError(
                    clarification
                    or "That search is too vague. Include what you need and when you need it."
                )
            parsed = _normalize(extracted, now)
            return _prepare_search_window(parsed, text, now)
        except VagueSearchError:
            raise
        except (HTTPError, URLError, TimeoutError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            pass
    _validate_search_query(text)
    return _prepare_search_window(parse_with_rules(text, now), text, now)


def _validate_search_query(text: str) -> None:
    lowered = " ".join(text.lower().split())
    has_resource = any(
        re.search(rf"\b{re.escape(phrase)}s?\b", lowered)
        for phrase in RESOURCE_TYPES
    )
    has_equipment = any(
        re.search(rf"\b{re.escape(phrase)}\b", lowered)
        for phrase in EQUIPMENT_KEYWORDS
    )
    has_time = bool(
        re.search(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b", lowered)
        or re.search(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b", lowered)
    )
    missing = []
    if not (has_resource or has_equipment):
        missing.append("a resource type or equipment need")
    if not has_time:
        missing.append("a time")
    if missing:
        needed = " and ".join(missing)
        raise VagueSearchError(
            f"That search is too vague. Please include {needed}, for example: "
            '"lab for 10 people tomorrow from 2pm to 4pm."'
        )


def parse_with_rules(text: str, now: datetime | None = None) -> dict[str, object]:
    now = now or datetime.now()
    lowered = " ".join(text.lower().split())

    resource_type = ""
    for phrase, value in RESOURCE_TYPES.items():
        if re.search(rf"\b{re.escape(phrase)}s?\b", lowered):
            resource_type = value
            break

    attendees_match = re.search(
        r"\b(\d+)\s*(?:people|persons|attendees|students|faculty|faculties|seats?)\b",
        lowered,
    )
    attendees = int(attendees_match.group(1)) if attendees_match else 1

    equipment = []
    for phrase, value in EQUIPMENT_KEYWORDS.items():
        if re.search(rf"\b{re.escape(phrase)}\b", lowered) and value not in equipment:
            equipment.append(value)

    target_date = _parse_date(lowered, now.date())
    try:
        start_time, end_time = _parse_times(lowered)
    except ValueError:
        start_time, end_time = None, None
    if start_time is None:
        start_time = time(10, 0)
    if end_time is None:
        duration = _parse_duration(lowered) or timedelta(hours=1)
        end_dt = datetime.combine(target_date, start_time) + duration
        end_time = end_dt.time()

    return {
        "type": resource_type,
        "attendees": max(1, attendees),
        "equipment": equipment,
        "date": target_date.isoformat(),
        "start_time": start_time.strftime("%H:%M"),
        "end_time": end_time.strftime("%H:%M"),
    }


def _parse_date(text: str, today: date) -> date:
    if "day after tomorrow" in text:
        return today + timedelta(days=2)
    if "tomorrow" in text:
        return today + timedelta(days=1)
    if "today" in text:
        return today
    iso_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if iso_match:
        try:
            return date.fromisoformat(iso_match.group(1))
        except ValueError:
            pass
    for name, weekday in WEEKDAYS.items():
        if re.search(rf"\b{name}\b", text):
            days_ahead = (weekday - today.weekday()) % 7
            return today + timedelta(days=days_ahead)
    return today


def _parse_times(text: str) -> tuple[time | None, time | None]:
    clock = r"\d{1,2}(?::\d{2})?\s*(?:am|pm)?"
    range_match = re.search(
        rf"(?:from\s+)?({clock})\s*(?:-|to|until|till)\s*({clock})", text
    )
    if range_match:
        first, second = range_match.groups()
        second_period = _period(second)
        return _clock_time(first, second_period), _clock_time(second)

    twelve_hour = re.search(r"\b(\d{1,2}(?::\d{2})?\s*(?:am|pm))\b", text)
    if twelve_hour:
        return _clock_time(twelve_hour.group(1)), None
    twenty_four_hour = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", text)
    if twenty_four_hour:
        return time(int(twenty_four_hour.group(1)), int(twenty_four_hour.group(2))), None
    return None, None


def _period(value: str) -> str | None:
    match = re.search(r"(am|pm)", value)
    return match.group(1) if match else None


def _clock_time(value: str, inherited_period: str | None = None) -> time:
    match = re.fullmatch(r"\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*", value)
    if not match:
        raise ValueError("Invalid time")
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    period = match.group(3) or inherited_period
    if period:
        if not 1 <= hour <= 12:
            raise ValueError("Invalid 12-hour time")
        hour = hour % 12 + (12 if period == "pm" else 0)
    if hour > 23 or minute > 59:
        raise ValueError("Invalid time")
    return time(hour, minute)


def _parse_duration(text: str) -> timedelta | None:
    hours = re.search(r"\bfor\s+(\d+(?:\.5)?)\s*hours?\b", text)
    if hours:
        return timedelta(hours=float(hours.group(1)))
    minutes = re.search(r"\bfor\s+(\d+)\s*minutes?\b", text)
    if minutes:
        return timedelta(minutes=int(minutes.group(1)))
    return None


def _prepare_search_window(
    values: dict[str, object], text: str, now: datetime
) -> dict[str, object]:
    target_date = date.fromisoformat(str(values["date"]))
    start = time.fromisoformat(str(values["start_time"]))
    end = time.fromisoformat(str(values["end_time"]))

    # People commonly write 12am for noon at the end of a morning range.
    if (
        start < time(12, 0)
        and end == time(0, 0)
        and re.search(r"(?:to|until|till|-)\s*12\s*am\b", text.lower())
    ):
        end = time(12, 0)

    start_dt = datetime.combine(target_date, start).replace(
        minute=(start.minute // 30) * 30, second=0, microsecond=0
    )
    end_dt = datetime.combine(target_date, end).replace(second=0, microsecond=0)
    if end_dt.minute not in (0, 30):
        end_dt = end_dt.replace(minute=(end_dt.minute // 30) * 30) + timedelta(
            minutes=30
        )

    if not _has_explicit_date(text) and start_dt < now:
        start_dt += timedelta(days=1)
        end_dt += timedelta(days=1)

    return {
        **values,
        "date": start_dt.date().isoformat(),
        "start_time": start_dt.strftime("%H:%M"),
        "end_time": end_dt.strftime("%H:%M"),
    }


def _has_explicit_date(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.search(r"\b(?:today|tomorrow|\d{4}-\d{2}-\d{2})\b", lowered)
        or any(re.search(rf"\b{name}\b", lowered) for name in WEEKDAYS)
    )


def _parse_with_llm(text: str, now: datetime, api_key: str) -> dict[str, object]:
    endpoint = os.getenv("LLM_API_URL") or (
        "https://api.groq.com/openai/v1/chat/completions"
    )
    model = os.getenv("LLM_MODEL", "openai/gpt-oss-20b")
    system_prompt = (
        "You interpret natural-language searches for Quorum, a campus resource booking system. "
        "Use the user's wording and the current India time to infer their practical booking intent. "
        "Understand typos, singular/plural forms, conversational phrasing, relative dates, and synonyms. "
        "Available resource types are lab, classroom, seminar_hall, and equipment. Infer the closest type: "
        "generic rooms and meeting rooms are classrooms; talks, presentations, and larger formal meetings "
        "usually need seminar_hall; experiments and computer practicals need lab. Extract explicitly requested "
        "equipment as lowercase underscore-separated values. Faculty, students, people, seats, and attendees "
        "can all describe the attendee count. Understand today, tomorrow, day after tomorrow, and weekdays. "
        "If no date is stated, use the next occurrence of the requested time. If only a start time is stated, "
        "use a one-hour duration. Interpret a morning range ending at 12am as noon, but preserve midnight for "
        "an evening or overnight range. Do not invent a resource need or a time when neither is implied. "
        "A request is actionable only when you can infer a resource type or equipment need and at least one time. "
        "If it is not actionable, set actionable to false and write one short clarification telling the user "
        "what is missing, with a useful example. Return only JSON with exactly these keys: actionable, "
        "clarification, type, attendees, equipment, date, start_time, end_time. type must be lab, classroom, "
        "seminar_hall, equipment, or an empty string. clarification must be empty when actionable is true. "
        "attendees must be a positive integer and defaults to 1 when unstated. equipment must be an array. "
        "date must be YYYY-MM-DD and times must be HH:MM."
    )
    user_prompt = (
        f"Current India date and time: {now.isoformat(timespec='minutes')}.\n"
        f"Campus resource search: {text}"
    )
    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }
    ).encode("utf-8")
    request = Request(
        endpoint,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Quorum/1.0",
        },
        method="POST",
    )
    with urlopen(request, timeout=8) as response:
        body = json.loads(response.read().decode("utf-8"))
    content = body["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content)
    return json.loads(content)


def _normalize(values: dict[str, object], now: datetime) -> dict[str, object]:
    resource_type = str(values.get("type", ""))
    if resource_type not in {"", "lab", "classroom", "seminar_hall", "equipment"}:
        resource_type = ""
    target_date = date.fromisoformat(str(values.get("date", now.date().isoformat())))
    start = time.fromisoformat(str(values.get("start_time", "10:00")))
    end = time.fromisoformat(str(values.get("end_time", "11:00")))
    attendees_value = values.get("attendees")
    attendees = max(1, int(attendees_value)) if attendees_value is not None else 1
    raw_equipment = values.get("equipment", [])
    if not isinstance(raw_equipment, list):
        raise ValueError("Equipment must be a list")
    equipment = [str(item).strip().lower().replace(" ", "_") for item in raw_equipment if str(item).strip()]
    return {
        "type": resource_type,
        "attendees": attendees,
        "equipment": equipment,
        "date": target_date.isoformat(),
        "start_time": start.strftime("%H:%M"),
        "end_time": end.strftime("%H:%M"),
    }
