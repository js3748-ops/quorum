import hashlib
import hmac
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from collections.abc import MutableMapping


PBKDF2_ITERATIONS = 260_000
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_LOCK_SECONDS = 15 * 60
LOGIN_MAX_FAILURES = 5
LOGIN_MAX_IP_FAILURES = 20
SESSION_IDLE_SECONDS = int(os.getenv("SESSION_IDLE_MINUTES", "30")) * 60
SESSION_ABSOLUTE_SECONDS = int(os.getenv("SESSION_ABSOLUTE_HOURS", "12")) * 60 * 60


def hash_password(password: str) -> tuple[str, str]:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return digest.hex(), salt.hex()


def verify_password(password: str, password_hash: str | None, password_salt: str | None) -> bool:
    if not password_hash or not password_salt:
        return False
    try:
        salt = bytes.fromhex(password_salt)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return hmac.compare_digest(digest.hex(), password_hash)


_DUMMY_PASSWORD_HASH, _DUMMY_PASSWORD_SALT = hash_password(
    secrets.token_urlsafe(24)
)


def verify_login_password(
    password: str, password_hash: str | None, password_salt: str | None
) -> bool:
    """Always run PBKDF2 so unknown emails do not have a fast failure path."""
    return verify_password(
        password,
        password_hash or _DUMMY_PASSWORD_HASH,
        password_salt or _DUMMY_PASSWORD_SALT,
    )


class LoginThrottle:
    def __init__(self):
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    @staticmethod
    def _identity_key(email: str, ip_address: str) -> str:
        value = f"{email.strip().lower()}\0{ip_address}".encode("utf-8")
        return f"identity:{hashlib.sha256(value).hexdigest()}"

    @staticmethod
    def _ip_key(ip_address: str) -> str:
        return f"ip:{ip_address}"

    def retry_after(
        self, email: str, ip_address: str, now: float | None = None
    ) -> int:
        now = time.monotonic() if now is None else now
        with self._lock:
            identity_wait = self._retry_after_key(
                self._identity_key(email, ip_address), LOGIN_MAX_FAILURES, now
            )
            ip_wait = self._retry_after_key(
                self._ip_key(ip_address), LOGIN_MAX_IP_FAILURES, now
            )
        return max(identity_wait, ip_wait)

    def record_failure(
        self, email: str, ip_address: str, now: float | None = None
    ) -> None:
        now = time.monotonic() if now is None else now
        with self._lock:
            for key in (
                self._identity_key(email, ip_address),
                self._ip_key(ip_address),
            ):
                attempts = self._failures[key]
                self._prune(attempts, now)
                attempts.append(now)

    def clear_identity(self, email: str, ip_address: str) -> None:
        with self._lock:
            self._failures.pop(self._identity_key(email, ip_address), None)

    def _retry_after_key(self, key: str, limit: int, now: float) -> int:
        attempts = self._failures.get(key)
        if not attempts:
            return 0
        self._prune(attempts, now)
        if len(attempts) < limit:
            return 0
        return max(1, round(LOGIN_LOCK_SECONDS - (now - attempts[-limit])))

    @staticmethod
    def _prune(attempts: deque[float], now: float) -> None:
        cutoff = now - LOGIN_WINDOW_SECONDS
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()


login_throttle = LoginThrottle()


def start_authenticated_session(
    session: MutableMapping[str, object], user_id: int, now: float | None = None
) -> None:
    now = time.time() if now is None else now
    session.clear()
    session.update(
        {
            "user_id": user_id,
            "session_id": secrets.token_urlsafe(32),
            "authenticated_at": now,
            "last_seen": now,
        }
    )


def authenticated_session_is_valid(
    session: MutableMapping[str, object], now: float | None = None
) -> bool:
    now = time.time() if now is None else now
    authenticated_at = session.get("authenticated_at")
    last_seen = session.get("last_seen")
    session_id = session.get("session_id")
    if (
        not isinstance(authenticated_at, (int, float))
        or not isinstance(last_seen, (int, float))
        or not isinstance(session_id, str)
        or not session_id
        or now - authenticated_at > SESSION_ABSOLUTE_SECONDS
        or now - last_seen > SESSION_IDLE_SECONDS
    ):
        session.clear()
        return False
    session["last_seen"] = now
    return True
