from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.auth import authenticated_session_is_valid
from backend.database import get_db
from backend.models import User


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    if not authenticated_session_is_valid(request.session):
        raise HTTPException(status_code=401, detail="Authentication required.")
    user_id = request.session.get("user_id")
    user = db.get(User, user_id) if isinstance(user_id, int) else None
    if not user or user.role == "background":
        request.session.clear()
        raise HTTPException(status_code=401, detail="Authentication required.")
    return user


def get_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required.")
    return user


def get_campus_admin(admin: User = Depends(get_admin)) -> User:
    if admin.admin_scope != "all":
        raise HTTPException(status_code=403, detail="Campus Admin access required.")
    return admin
