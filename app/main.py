from datetime import datetime

from fastapi import Depends, FastAPI, Form, HTTPException, Request as WebRequest, Response
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.database import get_db, init_db
from app.models import Request, Resource, Unavailability, User, Zone
from app.services import (
    create_booking_request,
    decide_request,
    parse_dt,
    parse_time,
    suggest_alternatives,
    validate_request_window,
)

app = FastAPI(title="Quorum")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.on_event("startup")
def startup():
    init_db()


def current_user(web_request: WebRequest, db: Session) -> User | None:
    user_id = web_request.cookies.get("user_id")
    if user_id and user_id.isdigit():
        user = db.get(User, int(user_id))
        if user:
            return user
    return db.scalars(select(User).order_by(User.id)).first()


def render(web_request: WebRequest, template: str, context: dict, db: Session):
    users = db.scalars(select(User).order_by(User.role, User.name)).all()
    user = current_user(web_request, db)
    base = {"request": web_request, "users": users, "current_user": user}
    base.update(context)
    return templates.TemplateResponse(template, base)


def require_admin(user: User | None):
    if not user or user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")


@app.get("/")
def home(web_request: WebRequest, db: Session = Depends(get_db)):
    return RedirectResponse("/resources", status_code=303)


@app.post("/switch-user")
def switch_user(user_id: int = Form(...)):
    response = RedirectResponse("/resources", status_code=303)
    response.set_cookie("user_id", str(user_id), max_age=60 * 60 * 24 * 7)
    return response


@app.get("/resources")
def resources(web_request: WebRequest, db: Session = Depends(get_db)):
    resources = db.scalars(
        select(Resource).options(joinedload(Resource.zone)).order_by(Resource.status, Resource.name)
    ).all()
    message = web_request.query_params.get("message")
    error = web_request.query_params.get("error")
    return render(
        web_request,
        "resources.html",
        {"resources": resources, "message": message, "error": error},
        db,
    )


@app.get("/resources/{resource_id}")
def resource_detail(resource_id: int, web_request: WebRequest, db: Session = Depends(get_db)):
    resource = db.scalars(
        select(Resource)
        .where(Resource.id == resource_id)
        .options(joinedload(Resource.zone), joinedload(Resource.unavailability))
    ).unique().first()
    if not resource:
        raise HTTPException(status_code=404)
    recent = db.scalars(
        select(Request)
        .where(Request.resource_id == resource_id)
        .options(joinedload(Request.user))
        .order_by(Request.start.desc())
        .limit(12)
    ).all()
    return render(
        web_request,
        "resource_detail.html",
        {"resource": resource, "recent": recent, "today": datetime.now().date()},
        db,
    )


@app.post("/requests")
def create_request(
    web_request: WebRequest,
    response: Response,
    resource_id: int = Form(...),
    start: str = Form(...),
    end: str = Form(...),
    attendees: int = Form(...),
    purpose: str = Form(""),
    db: Session = Depends(get_db),
):
    user = current_user(web_request, db)
    if not user:
        return RedirectResponse("/resources?error=Seed users before booking.", status_code=303)
    resource = db.get(Resource, resource_id)
    if not resource:
        raise HTTPException(status_code=404)
    start_dt = parse_dt(start)
    end_dt = parse_dt(end)
    created, conflict = create_booking_request(
        db,
        user_id=user.id,
        resource=resource,
        start=start_dt,
        end=end_dt,
        attendees=attendees,
        purpose=purpose,
    )
    if conflict:
        alternatives = suggest_alternatives(db, resource, start_dt, end_dt, attendees)
        return render(
            web_request,
            "conflict.html",
            {
                "resource": resource,
                "start": start_dt,
                "end": end_dt,
                "attendees": attendees,
                "purpose": purpose,
                "conflict": conflict,
                "alternatives": alternatives,
            },
            db,
        )
    return RedirectResponse(f"/requests/{created.id}/confirmation", status_code=303)


@app.get("/requests/{request_id}/confirmation")
def request_confirmation(
    request_id: int, web_request: WebRequest, db: Session = Depends(get_db)
):
    user = current_user(web_request, db)
    booking_request = db.scalars(
        select(Request)
        .where(Request.id == request_id)
        .options(joinedload(Request.resource).joinedload(Resource.zone))
    ).first()
    if not booking_request:
        raise HTTPException(status_code=404)
    if not user or (booking_request.user_id != user.id and user.role != "admin"):
        raise HTTPException(status_code=403, detail="This request belongs to another user")
    return render(
        web_request,
        "request_confirmation.html",
        {"booking_request": booking_request},
        db,
    )


@app.get("/my-requests")
def my_requests(web_request: WebRequest, db: Session = Depends(get_db)):
    user = current_user(web_request, db)
    if not user:
        raise HTTPException(status_code=404, detail="Seed users before viewing requests")
    requests = db.scalars(
        select(Request)
        .where(Request.user_id == user.id)
        .options(joinedload(Request.resource).joinedload(Resource.zone))
        .order_by(Request.created_at.desc())
    ).all()
    return render(web_request, "my_requests.html", {"requests": requests}, db)


@app.get("/admin/requests")
def admin_requests(web_request: WebRequest, db: Session = Depends(get_db)):
    require_admin(current_user(web_request, db))
    pending = db.scalars(
        select(Request)
        .where(Request.status == "pending")
        .options(joinedload(Request.user), joinedload(Request.resource).joinedload(Resource.zone))
        .order_by(Request.created_at, Request.id)
    ).all()
    return render(
        web_request,
        "admin_requests.html",
        {
            "pending": pending,
            "message": web_request.query_params.get("message"),
            "error": web_request.query_params.get("error"),
        },
        db,
    )


@app.post("/admin/requests/{request_id}/approve")
def approve_request(
    request_id: int, web_request: WebRequest, db: Session = Depends(get_db)
):
    admin = current_user(web_request, db)
    require_admin(admin)
    booking_request = db.get(Request, request_id)
    if not booking_request:
        raise HTTPException(status_code=404)
    error = decide_request(
        db, booking_request=booking_request, admin_id=admin.id, decision="approved"
    )
    target = "/admin/requests?error=Request+could+not+be+approved" if error else "/admin/requests?message=Request+approved"
    return RedirectResponse(target, status_code=303)


@app.post("/admin/requests/{request_id}/reject")
def reject_request(
    request_id: int,
    web_request: WebRequest,
    rejection_note: str = Form(""),
    db: Session = Depends(get_db),
):
    admin = current_user(web_request, db)
    require_admin(admin)
    booking_request = db.get(Request, request_id)
    if not booking_request:
        raise HTTPException(status_code=404)
    error = decide_request(
        db,
        booking_request=booking_request,
        admin_id=admin.id,
        decision="rejected",
        rejection_note=rejection_note,
    )
    target = "/admin/requests?error=Request+could+not+be+rejected" if error else "/admin/requests?message=Request+rejected"
    return RedirectResponse(target, status_code=303)


@app.get("/admin/resources")
def admin_resources(web_request: WebRequest, db: Session = Depends(get_db)):
    user = current_user(web_request, db)
    require_admin(user)
    resources = db.scalars(
        select(Resource).options(joinedload(Resource.zone)).order_by(Resource.name)
    ).all()
    zones = db.scalars(select(Zone).order_by(Zone.name)).all()
    return render(
        web_request,
        "admin_resources.html",
        {"resources": resources, "zones": zones},
        db,
    )


@app.post("/admin/resources")
def admin_create_resource(
    web_request: WebRequest,
    name: str = Form(...),
    type: str = Form(...),
    zone_id: int = Form(...),
    capacity: int = Form(...),
    equipment: str = Form(""),
    requires_approval: bool = Form(False),
    open_time: str = Form(...),
    close_time: str = Form(...),
    db: Session = Depends(get_db),
):
    require_admin(current_user(web_request, db))
    resource = Resource(
        name=name,
        type=type,
        zone_id=zone_id,
        capacity=capacity,
        equipment=[item.strip() for item in equipment.split(",") if item.strip()],
        requires_approval=requires_approval,
        status="active",
        open_time=parse_time(open_time),
        close_time=parse_time(close_time),
    )
    db.add(resource)
    db.commit()
    return RedirectResponse("/admin/resources", status_code=303)


@app.post("/admin/resources/{resource_id}")
def admin_update_resource(
    resource_id: int,
    web_request: WebRequest,
    name: str = Form(...),
    type: str = Form(...),
    zone_id: int = Form(...),
    capacity: int = Form(...),
    equipment: str = Form(""),
    requires_approval: bool = Form(False),
    status: str = Form(...),
    open_time: str = Form(...),
    close_time: str = Form(...),
    db: Session = Depends(get_db),
):
    require_admin(current_user(web_request, db))
    resource = db.get(Resource, resource_id)
    if not resource:
        raise HTTPException(status_code=404)
    resource.name = name
    resource.type = type
    resource.zone_id = zone_id
    resource.capacity = capacity
    resource.equipment = [item.strip() for item in equipment.split(",") if item.strip()]
    resource.requires_approval = requires_approval
    resource.status = status
    resource.open_time = parse_time(open_time)
    resource.close_time = parse_time(close_time)
    db.commit()
    return RedirectResponse("/admin/resources", status_code=303)


@app.post("/admin/resources/{resource_id}/unavailability")
def add_unavailability(
    resource_id: int,
    web_request: WebRequest,
    start: str = Form(...),
    end: str = Form(...),
    reason: str = Form(...),
    db: Session = Depends(get_db),
):
    require_admin(current_user(web_request, db))
    resource = db.get(Resource, resource_id)
    if not resource:
        raise HTTPException(status_code=404)
    start_dt = parse_dt(start)
    end_dt = parse_dt(end)
    error = validate_request_window(resource, start_dt, end_dt)
    if error and "active" not in error:
        return RedirectResponse(f"/admin/resources?error={error}", status_code=303)
    db.add(Unavailability(resource_id=resource_id, start=start_dt, end=end_dt, reason=reason))
    db.commit()
    return RedirectResponse("/admin/resources", status_code=303)
