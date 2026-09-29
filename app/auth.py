import hashlib
import hmac
import secrets


PBKDF2_ITERATIONS = 260_000


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
