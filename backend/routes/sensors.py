from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from backend.database import get_db
from backend.models import Resource, Sensor, User
from backend.routes.dependencies import get_admin
from backend.schemas import (
    MessageResponse,
    SensorCreate,
    SensorKeyResponse,
    SensorListResponse,
    SensorResponse,
    SensorUpdate,
)
from backend.services.admin_scope import admin_can_access_resource, scope_resource_query
from backend.services.occupancy import (
    as_india_aware,
    create_sensor,
    delete_sensor,
    rotate_sensor_key,
    sensor_status,
    update_sensor,
)


router = APIRouter(prefix="/api/sensors", tags=["Sensors"])

KEY_SHOWN_ONCE = "Store this key now. It will not be shown again."


def sensor_response(sensor: Sensor) -> SensorResponse:
    return SensorResponse(
        id=sensor.id,
        resource_id=sensor.resource_id,
        resource_name=sensor.resource.name,
        name=sensor.name,
        is_active=sensor.is_active,
        is_simulated=sensor.is_simulated,
        status=sensor_status(sensor),
        last_seen_at=as_india_aware(sensor.last_seen_at),
        created_at=as_india_aware(sensor.created_at),
    )


def scoped_sensor(db: Session, admin: User, sensor_id: int) -> Sensor:
    sensor = db.scalars(
        select(Sensor).where(Sensor.id == sensor_id).options(joinedload(Sensor.resource))
    ).first()
    if not sensor or not admin_can_access_resource(admin, sensor.resource):
        raise HTTPException(status_code=404, detail="Sensor not found.")
    return sensor


@router.post(
    "",
    response_model=SensorKeyResponse,
    status_code=201,
    summary="Register a sensor",
    description="Creates an occupancy sensor for a resource in the admin's scope and returns its API key once.",
)
def register_sensor(
    payload: SensorCreate,
    response: Response,
    admin=Depends(get_admin),
    db: Session = Depends(get_db),
):
    resource = db.get(Resource, payload.resource_id)
    if not resource or not admin_can_access_resource(admin, resource):
        raise HTTPException(status_code=404, detail="Resource not found.")
    sensor, key = create_sensor(
        db, resource=resource, name=payload.name, is_simulated=payload.is_simulated
    )
    response.headers["Cache-Control"] = "no-store"
    return {"sensor": sensor_response(sensor), "api_key": key, "message": KEY_SHOWN_ONCE}


@router.get(
    "",
    response_model=SensorListResponse,
    summary="List sensors",
    description="Lists sensors on resources in the admin's scope with status and last reading time.",
)
def list_sensors(admin=Depends(get_admin), db: Session = Depends(get_db)):
    query = (
        select(Sensor)
        .join(Sensor.resource)
        .options(joinedload(Sensor.resource))
        .order_by(Resource.name, Sensor.name, Sensor.id)
    )
    sensors = db.scalars(scope_resource_query(query, admin)).all()
    return {"sensors": [sensor_response(item) for item in sensors]}


@router.patch(
    "/{sensor_id}",
    response_model=SensorResponse,
    summary="Update a sensor",
    description="Renames a sensor or turns it on or off.",
)
def edit_sensor(
    sensor_id: int,
    payload: SensorUpdate,
    admin=Depends(get_admin),
    db: Session = Depends(get_db),
):
    sensor = scoped_sensor(db, admin, sensor_id)
    sensor = update_sensor(db, sensor, name=payload.name, is_active=payload.is_active)
    return sensor_response(sensor)


@router.post(
    "/{sensor_id}/rotate-key",
    response_model=SensorKeyResponse,
    summary="Rotate a sensor key",
    description="Replaces the sensor's API key. The old key stops working and the new key is shown once.",
)
def rotate_key(
    sensor_id: int,
    response: Response,
    admin=Depends(get_admin),
    db: Session = Depends(get_db),
):
    sensor = scoped_sensor(db, admin, sensor_id)
    key = rotate_sensor_key(db, sensor)
    response.headers["Cache-Control"] = "no-store"
    return {"sensor": sensor_response(sensor), "api_key": key, "message": KEY_SHOWN_ONCE}


@router.delete(
    "/{sensor_id}",
    response_model=MessageResponse,
    summary="Delete a sensor",
    description="Deletes a sensor and revokes its key. Past readings stay in the resource's history.",
)
def remove_sensor(
    sensor_id: int,
    admin=Depends(get_admin),
    db: Session = Depends(get_db),
):
    sensor = scoped_sensor(db, admin, sensor_id)
    delete_sensor(db, sensor)
    return {"message": "Sensor deleted."}
