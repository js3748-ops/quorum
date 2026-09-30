import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from http.cookiejar import CookieJar
from threading import Barrier
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

BASE_URL = os.getenv("QUORUM_API_URL", "http://127.0.0.1:8000")


class ApiResponse:
    def __init__(self, status_code: int, body: bytes):
        self.status_code = status_code
        self._body = body

    def json(self):
        return json.loads(self._body or b"null")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"API returned {self.status_code}: {self.json()}")


class ApiSession:
    def __init__(self):
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))

    def request(self, method: str, path: str, payload=None, params=None) -> ApiResponse:
        query = f"?{urlencode(params)}" if params else ""
        body = json.dumps(payload).encode() if payload is not None else None
        request = Request(
            f"{BASE_URL}{path}{query}",
            data=body,
            method=method,
            headers={"Content-Type": "application/json"} if body else {},
        )
        try:
            with self.opener.open(request) as response:
                return ApiResponse(response.status, response.read())
        except HTTPError as error:
            return ApiResponse(error.code, error.read())

    def get(self, path: str, params=None) -> ApiResponse:
        return self.request("GET", path, params=params)

    def post(self, path: str, json=None) -> ApiResponse:
        return self.request("POST", path, payload=json)

    def put(self, path: str, json=None) -> ApiResponse:
        return self.request("PUT", path, payload=json)


def login(email: str) -> tuple[ApiSession, dict]:
    session = ApiSession()
    response = session.post(
        "/api/auth/login",
        json={"email": email, "password": "demo1234"},
    )
    response.raise_for_status()
    return session, response.json()["user"]


def request_ids(session: ApiSession, path: str) -> list[int]:
    response = session.get(path)
    response.raise_for_status()
    return [item["id"] for item in response.json()["requests"]]


def main() -> None:
    student, _ = login("asha@quorum.local")
    day = (datetime.now() + timedelta(days=20)).date().isoformat()
    start = f"{day}T13:00"
    end = f"{day}T14:00"

    def find_resource(resource_type: str) -> dict:
        response = student.get(
            "/api/resources",
            params={
                "type": resource_type,
                "attendees": 5,
                "start": start,
                "end": end,
            },
        )
        response.raise_for_status()
        return response.json()["results"][0]["resource"]

    def book(resource: dict, purpose: str) -> dict:
        response = student.post(
            "/api/requests",
            json={
                "resource_id": resource["id"],
                "start": start,
                "end": end,
                "attendees": 5,
                "purpose": purpose,
                "confirmed": True,
            },
        )
        response.raise_for_status()
        return response.json()

    lab_request = book(find_resource("lab"), "Scoped admin lab request")
    seminar_request = book(
        find_resource("seminar_hall"), "Scoped admin seminar request"
    )

    emails = {
        "campus": "admin@quorum.local",
        "lab": "lab.coordinator@quorum.local",
        "facilities": "facilities@quorum.local",
    }
    sessions = {}
    users = {}
    for key, email in emails.items():
        sessions[key], users[key] = login(email)

    queues = {
        key: request_ids(session, "/api/admin/requests")
        for key, session in sessions.items()
    }
    all_requests = {
        key: request_ids(session, "/api/admin/all-requests")
        for key, session in sessions.items()
    }
    outside_detail = sessions["lab"].get(
        f"/api/admin/requests/{seminar_request['id']}"
    )
    outside_approve = sessions["lab"].post(
        f"/api/admin/requests/{seminar_request['id']}/approve",
        json={},
    )
    management = {
        key: {
            "users": session.get("/api/admin/users").status_code,
            "resources": session.get("/api/admin/resources").status_code,
        }
        for key, session in sessions.items()
    }
    campus = users["campus"]
    self_edit = sessions["campus"].put(
        f"/api/admin/users/{campus['id']}",
        json={
            "name": campus["name"],
            "email": campus["email"],
            "role": campus["role"],
            "department": campus["department"],
            "id_number": campus["id_number"],
            "year_of_study": None,
            "designation": campus["designation"],
            "admin_scope": campus["admin_scope"],
        },
    )
    profiles = {
        key: session.get("/api/auth/profile").json()
        for key, session in sessions.items()
    }
    scoped_types = {
        key: sorted(
            {item["type"] for item in session.get(
                "/api/admin/request-resources"
            ).json()}
        )
        for key, session in sessions.items()
    }

    assert lab_request["status"] == seminar_request["status"] == "pending"
    assert lab_request["id"] in queues["lab"]
    assert seminar_request["id"] not in queues["lab"]
    assert seminar_request["id"] in queues["facilities"]
    assert lab_request["id"] not in queues["facilities"]
    assert {lab_request["id"], seminar_request["id"]}.issubset(queues["campus"])
    assert lab_request["id"] in all_requests["lab"]
    assert seminar_request["id"] in all_requests["facilities"]
    assert outside_detail.status_code == outside_approve.status_code == 404
    assert management["campus"] == {"users": 200, "resources": 200}
    assert management["lab"] == management["facilities"] == {
        "users": 403,
        "resources": 403,
    }
    assert self_edit.status_code == 403
    assert scoped_types["lab"] == ["lab"]
    assert scoped_types["facilities"] == [
        "classroom",
        "equipment",
        "seminar_hall",
    ]
    assert all(
        profile["designation"]
        and profile["admin_scope"]
        and profile["year_of_study"] is None
        for profile in profiles.values()
    )

    barrier = Barrier(2)

    def approve_lab(key: str) -> int:
        barrier.wait()
        return sessions[key].post(
            f"/api/admin/requests/{lab_request['id']}/approve", json={}
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        decision_statuses = sorted(
            executor.map(approve_lab, ["campus", "lab"])
        )
    assert decision_statuses == [200, 409]

    print(
        json.dumps(
            {
                "requests": {
                    "lab": lab_request["id"],
                    "seminar": seminar_request["id"],
                    "status": "pending",
                },
                "queue_ids": queues,
                "lab_out_of_scope": {
                    "detail": outside_detail.status_code,
                    "approve": outside_approve.status_code,
                },
                "management": management,
                "campus_self_edit": self_edit.status_code,
                "scoped_resource_types": scoped_types,
                "simultaneous_decisions": decision_statuses,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
