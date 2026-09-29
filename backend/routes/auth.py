from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.auth import hash_password, verify_password
from backend.database import get_db
from backend.models import User
from backend.routes.dependencies import get_current_user
from backend.schemas import (
    AuthResponse,
    DemoLoginRequest,
    LoginRequest,
    MessageResponse,
    SignupRequest,
    UserResponse,
)


router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.get(
    "/me",
    response_model=AuthResponse,
    summary="Get the signed-in user",
    description="Returns the user stored in the signed session.",
)
def me(user: User = Depends(get_current_user)):
    return {"user": user}


@router.get(
    "/demo-accounts",
    response_model=list[UserResponse],
    summary="List demo accounts",
    description="Lists seeded accounts available through one-click demo login.",
)
def demo_accounts(db: Session = Depends(get_db)):
    return db.scalars(select(User).where(User.is_demo.is_(True)).order_by(User.role, User.name)).all()


@router.post(
    "/signup",
    response_model=AuthResponse,
    status_code=201,
    summary="Create an account",
    description="Creates a student or faculty account and starts a session.",
)
def signup(payload: SignupRequest, request: Request, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    name = payload.name.strip()
    if payload.role not in {"student", "faculty"}:
        raise HTTPException(status_code=400, detail="Choose faculty or student.")
    if not name:
        raise HTTPException(status_code=400, detail="Name is required.")
    if "@" not in email:
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    if len(payload.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status_code=409, detail="An account with that email already exists.")
    password_hash, password_salt = hash_password(payload.password)
    user = User(
        name=name,
        email=email,
        password_hash=password_hash,
        password_salt=password_salt,
        role=payload.role,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with that email already exists.")
    db.refresh(user)
    request.session.clear()
    request.session["user_id"] = user.id
    return {"user": user}


@router.post(
    "/login",
    response_model=AuthResponse,
    summary="Log in",
    description="Validates credentials and starts a signed session.",
)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email.strip().lower()))
    if not user or user.role == "background" or not verify_password(
        payload.password, user.password_hash, user.password_salt
    ):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    request.session.clear()
    request.session["user_id"] = user.id
    return {"user": user}


@router.post(
    "/demo-login",
    response_model=AuthResponse,
    summary="Use a demo account",
    description="Starts a session for a seeded demo account.",
)
def demo_login(payload: DemoLoginRequest, request: Request, db: Session = Depends(get_db)):
    user = db.scalar(
        select(User).where(
            User.email == payload.email.strip().lower(), User.is_demo.is_(True)
        )
    )
    if not user:
        raise HTTPException(status_code=404, detail="Demo account not found.")
    request.session.clear()
    request.session["user_id"] = user.id
    return {"user": user}


@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="Log out",
    description="Clears the current signed session.",
)
def logout(request: Request):
    request.session.clear()
    return {"message": "Logged out."}
