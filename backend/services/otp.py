import hashlib
import hmac
import os
import secrets
import smtplib
import ssl
from datetime import datetime, timedelta
from email.message import EmailMessage

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from backend.models import AuthChallenge


OTP_TTL_SECONDS = 10 * 60
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_SECONDS = 60
OTP_MAX_SENDS_PER_HOUR = 5


class EmailDeliveryError(RuntimeError):
    pass


class OtpRateLimitError(RuntimeError):
    pass


def create_otp_challenge(
    db: Session,
    *,
    purpose: str,
    email: str,
    user_id: int | None = None,
    context: dict | None = None,
) -> AuthChallenge:
    now = datetime.utcnow()
    recent = db.scalar(
        select(AuthChallenge)
        .where(
            AuthChallenge.email == email,
            AuthChallenge.purpose == purpose,
        )
        .order_by(AuthChallenge.created_at.desc())
    )
    sends_last_hour = db.scalar(
        select(func.count(AuthChallenge.id)).where(
            AuthChallenge.email == email,
            AuthChallenge.purpose == purpose,
            AuthChallenge.created_at > now - timedelta(hours=1),
        )
    )
    if recent and recent.created_at > now - timedelta(seconds=OTP_RESEND_SECONDS):
        raise OtpRateLimitError("Wait one minute before requesting another code.")
    if (sends_last_hour or 0) >= OTP_MAX_SENDS_PER_HOUR:
        raise OtpRateLimitError("Too many verification codes requested. Try again later.")
    db.execute(
        update(AuthChallenge)
        .where(
            AuthChallenge.email == email,
            AuthChallenge.purpose == purpose,
            AuthChallenge.consumed_at.is_(None),
        )
        .values(consumed_at=now)
        .execution_options(synchronize_session=False)
    )
    db.execute(
        delete(AuthChallenge).where(
            AuthChallenge.created_at < now - timedelta(days=1)
        )
    )
    challenge_id = secrets.token_urlsafe(32)
    otp = f"{secrets.randbelow(1_000_000):06d}"
    challenge = AuthChallenge(
        id=challenge_id,
        purpose=purpose,
        email=email,
        otp_digest=_otp_digest(challenge_id, otp),
        context=context,
        user_id=user_id,
        expires_at=now + timedelta(seconds=OTP_TTL_SECONDS),
    )
    db.add(challenge)
    db.flush()
    try:
        send_otp_email(email, otp, purpose)
        db.commit()
    except Exception as exc:
        db.rollback()
        if isinstance(exc, EmailDeliveryError):
            raise
        raise EmailDeliveryError("The verification email could not be sent.") from exc
    return challenge


def consume_otp_challenge(
    db: Session,
    *,
    challenge_id: str,
    otp: str,
    purpose: str,
) -> AuthChallenge | None:
    now = datetime.utcnow()
    challenge = db.get(AuthChallenge, challenge_id)
    if (
        not challenge
        or challenge.purpose != purpose
        or challenge.consumed_at is not None
        or challenge.expires_at <= now
        or challenge.attempts >= OTP_MAX_ATTEMPTS
    ):
        return None

    supplied_digest = _otp_digest(challenge_id, otp)
    if not hmac.compare_digest(supplied_digest, challenge.otp_digest):
        db.execute(
            update(AuthChallenge)
            .where(
                AuthChallenge.id == challenge_id,
                AuthChallenge.consumed_at.is_(None),
                AuthChallenge.attempts < OTP_MAX_ATTEMPTS,
            )
            .values(attempts=AuthChallenge.attempts + 1)
            .execution_options(synchronize_session=False)
        )
        db.commit()
        return None

    result = db.execute(
        update(AuthChallenge)
        .where(
            AuthChallenge.id == challenge_id,
            AuthChallenge.purpose == purpose,
            AuthChallenge.otp_digest == supplied_digest,
            AuthChallenge.consumed_at.is_(None),
            AuthChallenge.expires_at > now,
            AuthChallenge.attempts < OTP_MAX_ATTEMPTS,
        )
        .values(consumed_at=now)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        return None
    return challenge


def send_otp_email(email: str, otp: str, purpose: str) -> None:
    host = os.getenv("SMTP_HOST", "").strip()
    username = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_PASSWORD", "")
    sender = os.getenv("SMTP_FROM_EMAIL", "").strip() or username
    if not host or not sender:
        raise EmailDeliveryError(
            "Email verification is not configured. Set the SMTP environment variables."
        )

    use_ssl = _env_flag("SMTP_USE_SSL", False)
    use_starttls = _env_flag("SMTP_STARTTLS", not use_ssl)
    default_port = 465 if use_ssl else 587
    port = int(os.getenv("SMTP_PORT", str(default_port)))
    message = EmailMessage()
    message["From"] = sender
    message["To"] = email
    message["Subject"] = "Your Quorum verification code"
    action = "complete sign up" if purpose == "signup" else "complete login"
    message.set_content(
        f"Your Quorum verification code is {otp}.\n\n"
        f"Use it within 10 minutes to {action}. If you did not request this, ignore this email."
    )

    context = ssl.create_default_context()
    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=10, context=context) as smtp:
                if username:
                    smtp.login(username, password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=10) as smtp:
                smtp.ehlo()
                if use_starttls:
                    smtp.starttls(context=context)
                    smtp.ehlo()
                if username:
                    smtp.login(username, password)
                smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise EmailDeliveryError("The verification email could not be sent.") from exc


def _otp_digest(challenge_id: str, otp: str) -> str:
    secret = (
        os.getenv("OTP_SECRET")
        or os.getenv("SESSION_SECRET")
        or "local-development-only-change-me"
    )
    return hmac.new(
        secret.encode("utf-8"),
        f"{challenge_id}:{otp}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
