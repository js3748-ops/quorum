import json
import os
from datetime import datetime, timedelta

os.environ.setdefault("QUORUM_API_URL", "http://127.0.0.1:8000")

from admin_scope_test import BASE_URL, ApiSession, login  # noqa: E402


def main() -> None:
    student, _ = login("asha@quorum.local")
    campus, _ = login("admin@quorum.local")
    lab_admin, _ = login("lab.coordinator@quorum.local")
    facilities, _ = login("facilities@quorum.local")
    day = (datetime.now() + timedelta(days=20)).date().isoformat()
    start = f"{day}T15:00"
    end = f"{day}T16:00"

    search = student.get(
        "/api/resources",
        params={
            "type": "classroom",
            "attendees": 4,
            "start": start,
            "end": end,
        },
    )
    search.raise_for_status()
    resource = search.json()["results"][0]["resource"]
    created = student.post(
        "/api/requests",
        json={
            "resource_id": resource["id"],
            "start": start,
            "end": end,
            "attendees": 4,
            "purpose": "History and hold integration test",
            "confirmed": True,
        },
    )
    created.raise_for_status()
    request_id = created.json()["id"]
    approved = campus.post(f"/api/admin/requests/{request_id}/approve", json={})
    approved.raise_for_status()

    expected_back = (datetime.now() + timedelta(days=40)).date().isoformat()
    hold_payload = {
        "reason": "Safety inspection",
        "expected_back": expected_back,
    }
    preview = campus.post(
        f"/api/admin/resources/{resource['id']}/hold", json=hold_payload
    )
    assert preview.status_code == 409
    affected = preview.json()["detail"]["affected_requests"]
    assert [item["id"] for item in affected] == [request_id]
    hold_payload["confirmed_request_ids"] = [request_id]
    held = campus.post(
        f"/api/admin/resources/{resource['id']}/hold", json=hold_payload
    )
    held.raise_for_status()
    assert held.json()["status"] == "on_hold"

    student_request = student.get(f"/api/requests/{request_id}")
    student_request.raise_for_status()
    item = student_request.json()
    assert item["status"] == "cancelled"
    assert item["status_reason"] == "Resource on hold: Safety inspection"
    assert [event["event"] for event in item["events"]] == [
        "created",
        "approved",
        "auto_cancelled_hold",
    ]

    admin_booking = campus.post(
        "/api/requests",
        json={
            "resource_id": resource["id"],
            "start": start,
            "end": end,
            "attendees": 1,
            "purpose": "Admin booking must be rejected",
            "confirmed": True,
        },
    )
    assert admin_booking.status_code == 403

    history_filters = {
        "status": "cancelled",
        "resource_id": resource["id"],
        "requester_id": item["user_id"],
        "deciding_admin_id": item["decided_by"],
        "date_from": datetime.now().date().isoformat(),
        "date_to": datetime.now().date().isoformat(),
        "q": "Safety inspection",
    }
    facilities_history = facilities.get("/api/admin/history", params=history_filters)
    facilities_history.raise_for_status()
    assert [row["id"] for row in facilities_history.json()["requests"]] == [request_id]
    lab_history = lab_admin.get("/api/admin/history", params=history_filters)
    lab_history.raise_for_status()
    assert lab_history.json()["requests"] == []
    csv_response = facilities.get("/api/admin/history.csv", params=history_filters)
    csv_response.raise_for_status()
    csv_text = csv_response._body.decode()
    assert "History and hold integration test" in csv_text
    assert "CANCELLED" in csv_text
    lab_csv = lab_admin.get("/api/admin/history.csv", params=history_filters)
    lab_csv.raise_for_status()
    assert "History and hold integration test" not in lab_csv._body.decode()

    dashboard = student.get("/api/dashboard")
    dashboard.raise_for_status()
    dashboard_data = dashboard.json()
    assert len(dashboard_data["quieter_zones"]) == 5
    assert any(row["id"] == resource["id"] for row in dashboard_data["holds"])
    admin_home = campus.get("/api/admin/home")
    admin_home.raise_for_status()
    assert any(row["id"] == resource["id"] for row in admin_home.json()["holds"])

    default_results = student.get(
        "/api/resources",
        params={"type": "classroom", "attendees": 4, "start": start, "end": end},
    ).json()["results"]
    hold_results = student.get(
        "/api/resources",
        params={
            "type": "classroom",
            "attendees": 4,
            "start": start,
            "end": end,
            "show_on_hold": "true",
        },
    ).json()["results"]
    assert resource["id"] not in {row["resource"]["id"] for row in default_results}
    assert resource["id"] in {row["resource"]["id"] for row in hold_results}

    lifted = campus.post(
        f"/api/admin/resources/{resource['id']}/lift-hold", json={}
    )
    lifted.raise_for_status()
    second_student, _ = login("kabir@quorum.local")
    replacement = second_student.post(
        "/api/requests",
        json={
            "resource_id": resource["id"],
            "start": start,
            "end": end,
            "attendees": 4,
            "purpose": "Replacement after released hold slot",
            "confirmed": True,
        },
    )
    replacement.raise_for_status()

    print(
        json.dumps(
            {
                "admin_booking": admin_booking.status_code,
                "hold_preview": preview.status_code,
                "cancelled_request": {
                    "id": request_id,
                    "reason": item["status_reason"],
                    "events": [event["event"] for event in item["events"]],
                },
                "history": {
                    "facilities": len(facilities_history.json()["requests"]),
                    "lab": len(lab_history.json()["requests"]),
                    "csv": True,
                },
                "quieter_zones": len(dashboard_data["quieter_zones"]),
                "hold_hidden_by_default": True,
                "released_slot_rebooked": replacement.status_code,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
