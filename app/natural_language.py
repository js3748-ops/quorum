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


def parse_natural_language(text: str, now: datetime | None = None) -> dict[str, object]:
    now = now or datetime.now()
    api_key = os.getenv("LLM_API_KEY")
    if api_key:
        try:
            return _normalize(_parse_with_llm(text, now, api_key), now)
        except (HTTPError, URLError, TimeoutError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            pass
    return parse_with_rules(text, now)


def parse_with_rules(text: str, now: datetime | None = None) -> dict[str, object]:
    now = now or datetime.now()
    lowered = " ".join(text.lower().split())

    resource_type = ""
    for phrase, value in RESOURCE_TYPES.items():
        if re.search(rf"\b{re.escape(phrase)}s?\b", lowered):
            resource_type = value
            break

    attendees_match = re.search(
        r"\b(\d+)\s*(?:people|persons|attendees|students|seats?)\b", lowered
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
    range_match = re.search(rf"(?:from\s+)?({clock})\s*(?:-|to|until)\s*({clock})", text)
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


def _parse_with_llm(text: str, now: datetime, api_key: str) -> dict[str, object]:
    endpoint = os.getenv("LLM_API_URL", "https://api.openai.com/v1/chat/completions")
    model = os.getenv("LLM_MODEL", "gpt-4o-mini")
    prompt = (
        "Extract a campus resource search. Return only a JSON object with exactly these keys: "
        "type, attendees, equipment, date, start_time, end_time. "
        "type must be lab, classroom, seminar_hall, equipment, or an empty string. "
        "equipment must be an array of lowercase strings. date must be YYYY-MM-DD and times HH:MM. "
        f"Today is {now.date().isoformat()}. Search: {text}"
    )
    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }
    ).encode("utf-8")
    request = Request(
        endpoint,
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
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
    attendees = max(1, int(values.get("attendees", 1)))
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
