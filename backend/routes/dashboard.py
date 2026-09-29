from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.routes.dependencies import get_admin
from backend.schemas import DashboardResponse
from backend.services.analytics import current_week_dashboard


router = APIRouter(prefix="/api/admin", tags=["Analytics"])


@router.get(
    "/dashboard",
    response_model=DashboardResponse,
    summary="Get utilization analytics",
    description="Returns weekly request counts, peak hours, zone load, and resource utilization.",
)
def dashboard(admin=Depends(get_admin), db: Session = Depends(get_db)):
    return current_week_dashboard(db)
