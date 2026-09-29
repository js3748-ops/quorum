import os
from datetime import datetime, time, timedelta

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Form, HTTPException, Request as WebRequest
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload
from starlette.middleware.sessions import SessionMiddleware

from app.analytics import current_week_dashboard, ranked_resources
from app.auth import hash_password, verify_password
from app.database import SessionLocal, get_db, init_db
from app.models import Request, Resource, Unavailability, User, Zone
from app.natural_language import parse_natural_language
from app.services import (
    create_booking_request,
    decide_request,
    parse_dt,
    parse_time,
    suggest_alternatives,
    validate_request_window,
)

load_dotenv()

app = FastAPI(title="Quorum")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
templates.env.filters["readable"] = lambda value: str(value).replace("_", " ")


class AdminOnlyError(Exception):
    pass


@app.on_event("startup")
def startup():
    init_db()


def current_user(web_request: WebRequest, db: Session) -> User | None:
    user_id = web_request.session.get("user_id")
    if isinstance(user_id, int):
        user = db.get(User, user_id)
        if user and user.role != "background":
            return user
    return None


def render(
    web_request: WebRequest,
    template: str,
    context: dict,
    db: Session,
    status_code: int = 200,
):
    user = current_user(web_request, db)
    base = {"request": web_request, "current_user": user}
    base.update(context)
    return templates.TemplateResponse(template, base, status_code=status_code)


def require_admin(user: User | None):
    if not user or user.role != "admin":
        raise AdminOnlyError


@app.exception_handler(AdminOnlyError)
def admin_only_page(web_request: WebRequest, _error: AdminOnlyError):
    db = SessionLocal()
    try:
        return render(web_request, "forbidden.html", {}, db, status_code=403)
    finally:
        db.close()


@app.middleware("http")
async def require_login(web_request: WebRequest, call_next):
    public_paths = {"/", "/login", "/login/demo", "/signup"}
    if web_request.url.path in public_paths or web_request.url.path.startswith("/static/"):
        return await call_next(web_request)
    user_id = web_request.session.get("user_id")
    if not isinstance(user_id, int):
        return RedirectResponse("/login", status_code=303)
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if not user or user.role == "background":
            web_request.session.clear()
            return RedirectResponse("/login", status_code=303)
    return await call_next(web_request)


# Local development only. Production deployments must set SESSION_SECRET.
SESSION_SECRET = os.getenv("SESSION_SECRET") or "local-development-only-change-me"
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    same_site="lax",
    https_only=False,
    max_age=60 * 60 * 24 * 7,
)


@app.get("/")
def home(web_request: WebRequest, db: Session = Depends(get_db)):
    return render(web_request, "landing.html", {}, db)


@app.get("/signup")
def signup_page(web_request: WebRequest, db: Session = Depends(get_db)):
    return render(web_request, "signup.html", {"form": {}}, db)


@app.post("/signup")
def signup(
    web_request: WebRequest,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    db: Session = Depends(get_db),
):
    form = {"name": name.strip(), "email": email.strip(), "role": role}
    normalized_email = email.strip().lower()
    if role not in {"faculty", "student"}:
        return render(web_request, "signup.html", {"error": "Choose faculty or student.", "form": form}, db, 400)
    if len(password) < 8:
        return render(web_request, "signup.html", {"error": "Password must be at least 8 characters.", "form": form}, db, 400)
    if db.scalar(select(User.id).where(User.email == normalized_email)):
        return render(web_request, "signup.html", {"error": "An account with that email already exists.", "form": form}, db, 400)
    password_hash, password_salt = hash_password(password)
    user = User(
        name=name.strip(),
        email=normalized_email,
        password_hash=password_hash,
        password_salt=password_salt,
        role=role,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return render(web_request, "signup.html", {"error": "An account with that email already exists.", "form": form}, db, 400)
    db.refresh(user)
    web_request.session.clear()
    web_request.session["user_id"] = user.id
    return RedirectResponse("/resources", status_code=303)


@app.get("/login")
def login_page(web_request: WebRequest, db: Session = Depends(get_db)):
    demos = db.scalars(
        select(User).where(User.is_demo.is_(True)).order_by(User.role, User.name)
    ).all()
    return render(web_request, "login.html", {"demos": demos}, db)


@app.post("/login")
def login(
    web_request: WebRequest,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    normalized_email = email.strip().lower()
    user = db.scalar(select(User).where(User.email == normalized_email))
    if not user or user.role == "background" or not verify_password(password, user.password_hash, user.password_salt):
        demos = db.scalars(select(User).where(User.is_demo.is_(True)).order_by(User.role, User.name)).all()
        return render(
            web_request,
            "login.html",
            {"error": "Email or password is incorrect.", "email": email.strip(), "demos": demos},
            db,
            400,
        )
    web_request.session.clear()
    web_request.session["user_id"] = user.id
    target = "/admin/requests" if user.role == "admin" else "/resources"
    return RedirectResponse(target, status_code=303)


@app.post("/login/demo")
def demo_login(
    web_request: WebRequest,
    email: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.scalar(
        select(User).where(User.email == email.strip().lower(), User.is_demo.is_(True))
    )
    if not user:
        raise HTTPException(status_code=404)
    web_request.session.clear()
    web_request.session["user_id"] = user.id
    target = "/admin/requests" if user.role == "admin" else "/resources"
    return RedirectResponse(target, status_code=303)


@app.get("/logout")
def logout(web_request: WebRequest):
    web_request.session.clear()
    return RedirectResponse("/", status_code=303)


@app.get("/resources")
def resources(web_request: WebRequest, db: Session = Depends(get_db)):
    now = datetime.now()
    week_start = datetime.combine((now - timedelta(days=now.weekday())).date(), time.min)
    default_start = week_start + timedelta(days=2, hours=10)
    query_text = web_request.query_params.get("q", "").strip()
    if query_text:
        parsed = parse_natural_language(query_text, now)
        resource_type = str(parsed["type"])
        attendees_value = str(parsed["attendees"])
        equipment_value = ", ".join(parsed["equipment"])
        start_value = f"{parsed['date']}T{parsed['start_time']}"
        end_value = f"{parsed['date']}T{parsed['end_time']}"
    else:
        resource_type = web_request.query_params.get("type", "lab")
        attendees_value = web_request.query_params.get("attendees", "18")
        equipment_value = web_request.query_params.get("equipment", "")
        start_value = web_request.query_params.get(
            "start", default_start.strftime("%Y-%m-%dT%H:%M")
        )
        end_value = web_request.query_params.get(
            "end", (default_start + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
        )
    try:
        attendees = max(1, int(attendees_value))
        start_dt = parse_dt(start_value)
        end_dt = parse_dt(end_value)
        if end_dt <= start_dt:
            raise ValueError
        equipment = [item.strip() for item in equipment_value.split(",") if item.strip()]
        results = ranked_resources(
            db,
            resource_type=resource_type,
            attendees=attendees,
            equipment=equipment,
            start=start_dt,
            end=end_dt,
        )
        error = web_request.query_params.get("error")
    except ValueError:
        results = []
        attendees = 18
        error = "Choose a valid time range."
    message = web_request.query_params.get("message")
    return render(
        web_request,
        "resources.html",
        {
            "results": results,
            "message": message,
            "error": error,
            "query_text": query_text,
            "filters": {
                "type": resource_type,
                "attendees": attendees,
                "equipment": equipment_value,
                "start": start_value,
                "end": end_value,
            },
        },
        db,
    )


@app.get("/dashboard")
def dashboard(web_request: WebRequest, db: Session = Depends(get_db)):
    require_admin(current_user(web_request, db))
    return render(
        web_request,
        "dashboard.html",
        {"dashboard": current_week_dashboard(db)},
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
    resource_id: int = Form(...),
    start: str = Form(...),
    end: str = Form(...),
    attendees: int = Form(...),
    purpose: str = Form(""),
    db: Session = Depends(get_db),
):
    user = current_user(web_request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    resource = db.get(Resource, resource_id)
    if not resource:
        raise HTTPException(status_code=404)
    start_dt = parse_dt(start)
    end_dt = parse_dt(end)
    created, conflict = create_booking_request(
        db,
        user_id=user.id,
        user_role=user.role,
        resource=resource,
        start=start_dt,
        end=end_dt,
        attendees=attendees,
        purpose=purpose,
    )
    if conflict:
        outside_open_hours = (
            start_dt.date() != end_dt.date()
            or start_dt.time() < resource.open_time
            or end_dt.time() > resource.close_time
        )
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
                "conflict_title": "Outside open hours" if outside_open_hours else "Conflict",
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
    status_filter = web_request.query_params.get("status", "all")
    if status_filter not in {"all", "pending", "approved", "rejected"}:
        status_filter = "all"
    query = (
        select(Request)
        .where(Request.user_id == user.id)
        .options(joinedload(Request.resource).joinedload(Resource.zone))
        .order_by(Request.created_at.desc(), Request.id.desc())
    )
    if status_filter != "all":
        query = query.where(Request.status == status_filter)
    requests = db.scalars(query).all()
    return render(
        web_request,
        "my_requests.html",
        {"requests": requests, "status_filter": status_filter},
        db,
    )


@app.get("/admin/requests")
def admin_requests(web_request: WebRequest, db: Session = Depends(get_db)):
    require_admin(current_user(web_request, db))
    pending = db.scalars(
        select(Request)
        .join(Request.user)
        .where(Request.status == "pending", User.role != "background")
        .options(joinedload(Request.user), joinedload(Request.resource).joinedload(Resource.zone))
        .order_by(Request.created_at.desc(), Request.id.desc())
    ).all()
    return render(
        web_request,
        "admin_requests.html",
        {
            "pending": pending,
            "new_cutoff": datetime.utcnow() - timedelta(hours=1),
            "message": web_request.query_params.get("message"),
            "error": web_request.query_params.get("error"),
        },
        db,
    )


@app.get("/admin/all-requests")
def admin_all_requests(web_request: WebRequest, db: Session = Depends(get_db)):
    require_admin(current_user(web_request, db))
    status_filter = web_request.query_params.get("status", "all")
    role_filter = web_request.query_params.get("role", "all")
    resource_value = web_request.query_params.get("resource", "all")
    if status_filter not in {"all", "pending", "approved", "rejected", "cancelled"}:
        status_filter = "all"
    if role_filter not in {"all", "student", "faculty", "admin"}:
        role_filter = "all"
    resource_id = int(resource_value) if resource_value.isdigit() else None

    query = (
        select(Request)
        .join(Request.user)
        .where(User.role != "background")
        .options(joinedload(Request.user), joinedload(Request.resource).joinedload(Resource.zone))
        .order_by(Request.created_at.desc(), Request.id.desc())
    )
    if status_filter != "all":
        query = query.where(Request.status == status_filter)
    if role_filter != "all":
        query = query.where(User.role == role_filter)
    if resource_id is not None:
        query = query.where(Request.resource_id == resource_id)

    requests = db.scalars(query).all()
    resources = db.scalars(select(Resource).order_by(Resource.name)).all()
    return render(
        web_request,
        "admin_all_requests.html",
        {
            "requests": requests,
            "resources": resources,
            "filters": {
                "status": status_filter,
                "role": role_filter,
                "resource": resource_id,
            },
        },
        db,
    )


@app.post("/admin/requests/{request_id}/approve")
def approve_request(
    request_id: int,
    web_request: WebRequest,
    db: Session = Depends(get_db),
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
