from sqlalchemy.sql import Select

from backend.models import Resource, User


ADMIN_SCOPE_TYPES = {
    "all": {"lab", "classroom", "seminar_hall", "equipment"},
    "labs": {"lab"},
    "facilities": {"classroom", "seminar_hall", "equipment"},
}

ADMIN_SCOPE_LABELS = {
    "all": "All resources",
    "labs": "Labs",
    "facilities": "Classrooms, seminar halls and equipment",
}


def resource_types_for_admin(admin: User) -> set[str]:
    return ADMIN_SCOPE_TYPES.get(admin.admin_scope or "", set())


def admin_can_access_resource(admin: User, resource: Resource) -> bool:
    return resource.type in resource_types_for_admin(admin)


def scope_resource_query(query: Select, admin: User) -> Select:
    if admin.admin_scope == "all":
        return query
    return query.where(Resource.type.in_(resource_types_for_admin(admin)))
