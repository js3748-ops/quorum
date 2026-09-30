import os

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.auth import (
    hash_password,
    login_throttle,
    start_authenticated_session,
    verify_login_password,
)
from backend.database import get_db
from backend.models import User
from backend.routes.dependencies import get_current_user
from backend.schemas import (
    AuthChallengeResponse,
    AuthResponse,
    DemoLoginRequest,
    LoginRequest,
    MessageResponse,
    OtpVerifyRequest,
    SignupRequest,
    UserResponse,
)
from backend.services.otp import (
    EmailDeliveryError,
    OTP_TTL_SECONDS,
    OtpRateLimitError,
    consume_otp_challenge,
    create_otp_challenge,
)


router = APIRouter(prefix="/api/auth", tags=["Authentication"])
DEMO_MODE = os.getenv("DEMO_MODE", "true").strip().lower() in {"1", "true", "yes", "on"}


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
    if not DEMO_MODE:
        return []
    return db.scalars(select(User).where(User.is_demo.is_(True)).order_by(User.role, User.name)).all()


@router.post(
    "/signup",
    response_model=AuthChallengeResponse,
    status_code=202,
    summary="Start account creation",
    description="Validates signup details and emails a single-use verification code.",
)
def signup(payload: SignupRequest, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    name = payload.name.strip()
    id_number = payload.id_number.strip().upper()
    if payload.role not in {"student", "faculty"}:
        raise HTTPException(status_code=400, detail="Choose faculty or student.")
    if not name:
        raise HTTPException(status_code=400, detail="Name is required.")
    if not id_number:
        raise HTTPException(status_code=400, detail="ID number is required.")
    if "@" not in email:
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    if len(payload.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status_code=409, detail="An account with that email already exists.")
    if db.scalar(select(User.id).where(User.id_number == id_number)):
        raise HTTPException(status_code=409, detail="That ID number is already registered.")
    password_hash, password_salt = hash_password(payload.password)
    try:
        challenge = create_otp_challenge(
            db,
            purpose="signup",
            email=email,
            context={
                "name": name,
                "email": email,
                "password_hash": password_hash,
                "password_salt": password_salt,
                "role": payload.role,
                "department": payload.department,
                "id_number": id_number,
                "year_of_study": payload.year_of_study,
            },
        )
    except OtpRateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    except EmailDeliveryError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {
        "challenge_id": challenge.id,
        "message": f"A verification code was sent to {email}.",
        "expires_in_seconds": OTP_TTL_SECONDS,
    }


@router.post(
    "/signup/verify",
    response_model=AuthResponse,
    status_code=201,
    summary="Verify account creation",
    description="Consumes the emailed code, creates the account, and starts a signed session.",
)
def verify_signup(
    payload: OtpVerifyRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    challenge = consume_otp_challenge(
        db,
        challenge_id=payload.challenge_id,
        otp=payload.otp,
        purpose="signup",
    )
    if not challenge or not challenge.context:
        raise HTTPException(status_code=400, detail="The code is incorrect or has expired.")
    values = challenge.context
    if db.scalar(select(User.id).where(User.email == values["email"])):
        db.rollback()
        raise HTTPException(status_code=409, detail="That account has already been created.")
    if db.scalar(select(User.id).where(User.id_number == values["id_number"])):
        db.rollback()
        raise HTTPException(status_code=409, detail="That ID number is already registered.")
    user = User(**values)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="That email or ID number is already registered.")
    db.refresh(user)
    start_authenticated_session(request.session, user.id)
    return {"user": user}


@router.get(
    "/profile",
    response_model=UserResponse,
    summary="Get my profile",
    description="Returns the signed-in user's locked profile details.",
)
def profile(user: User = Depends(get_current_user)):
    return user


@router.post(
    "/login",
    response_model=AuthChallengeResponse,
    status_code=202,
    summary="Start login",
    description="Validates credentials and emails a single-use verification code.",
)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    ip_address = request.client.host if request.client else "unknown"
    retry_after = login_throttle.retry_after(email, ip_address)
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Try again in a few minutes.",
            headers={"Retry-After": str(retry_after)},
        )

    user = db.scalar(select(User).where(User.email == email))
    password_matches = verify_login_password(
        payload.password,
        user.password_hash if user else None,
        user.password_salt if user else None,
    )
    if not user or user.role == "background" or not password_matches:
        login_throttle.record_failure(email, ip_address)
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    login_throttle.clear_identity(email, ip_address)
    try:
        challenge = create_otp_challenge(
            db,
            purpose="login",
            email=email,
            user_id=user.id,
        )
    except OtpRateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    except EmailDeliveryError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {
        "challenge_id": challenge.id,
        "message": f"A verification code was sent to {email}.",
        "expires_in_seconds": OTP_TTL_SECONDS,
    }


@router.post(
    "/login/verify",
    response_model=AuthResponse,
    summary="Verify login",
    description="Consumes the emailed code and starts a signed session.",
)
def verify_login(
    payload: OtpVerifyRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    challenge = consume_otp_challenge(
        db,
        challenge_id=payload.challenge_id,
        otp=payload.otp,
        purpose="login",
    )
    if not challenge or challenge.user_id is None:
        raise HTTPException(status_code=400, detail="The code is incorrect or has expired.")
    user = db.get(User, challenge.user_id)
    if not user or user.role == "background":
        db.rollback()
        raise HTTPException(status_code=400, detail="The code is incorrect or has expired.")
    db.commit()
    start_authenticated_session(request.session, user.id)
    return {"user": user}


@router.post(
    "/demo-login",
    response_model=AuthResponse,
    summary="Use a demo account",
    description="Starts a session for a seeded demo account.",
)
def demo_login(payload: DemoLoginRequest, request: Request, db: Session = Depends(get_db)):
    if not DEMO_MODE:
        raise HTTPException(status_code=404, detail="Demo login is disabled.")
    user = db.scalar(
        select(User).where(
            User.email == payload.email.strip().lower(), User.is_demo.is_(True)
        )
    )
    if not user:
        raise HTTPException(status_code=404, detail="Demo account not found.")
    start_authenticated_session(request.session, user.id)
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
