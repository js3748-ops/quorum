import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker


ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")
DEFAULT_DATABASE_URL = f"sqlite:///{ROOT_DIR / 'quorum.db'}"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from backend import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    request_columns = {column["name"] for column in inspect(engine).get_columns("requests")}
    if "rejection_note" not in request_columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE requests ADD COLUMN rejection_note TEXT"))
    if "status_reason" not in request_columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE requests ADD COLUMN status_reason TEXT"))
    user_columns = {column["name"] for column in inspect(engine).get_columns("users")}
    migrations = {
        "email": "ALTER TABLE users ADD COLUMN email VARCHAR(255)",
        "password_hash": "ALTER TABLE users ADD COLUMN password_hash VARCHAR(64)",
        "password_salt": "ALTER TABLE users ADD COLUMN password_salt VARCHAR(32)",
        "is_demo": "ALTER TABLE users ADD COLUMN is_demo BOOLEAN NOT NULL DEFAULT 0",
        "department": "ALTER TABLE users ADD COLUMN department VARCHAR(40)",
        "id_number": "ALTER TABLE users ADD COLUMN id_number VARCHAR(80)",
        "year_of_study": "ALTER TABLE users ADD COLUMN year_of_study INTEGER",
        "designation": "ALTER TABLE users ADD COLUMN designation VARCHAR(120)",
        "admin_scope": "ALTER TABLE users ADD COLUMN admin_scope VARCHAR(30)",
        "member_since": "ALTER TABLE users ADD COLUMN member_since DATETIME",
    }
    with engine.begin() as connection:
        for column, statement in migrations.items():
            if column not in user_columns:
                connection.execute(text(statement))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email ON users (email)"))
        connection.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_id_number ON users (id_number)")
        )
    request_migrations = {
        "confirmed_at": "ALTER TABLE requests ADD COLUMN confirmed_at DATETIME",
    }
    with engine.begin() as connection:
        for column, statement in request_migrations.items():
            if column not in request_columns:
                connection.execute(text(statement))
    resource_columns = {column["name"] for column in inspect(engine).get_columns("resources")}
    resource_migrations = {
        "hold_reason": "ALTER TABLE resources ADD COLUMN hold_reason TEXT",
        "expected_back": "ALTER TABLE resources ADD COLUMN expected_back DATE",
    }
    with engine.begin() as connection:
        for column, statement in resource_migrations.items():
            if column not in resource_columns:
                connection.execute(text(statement))
        connection.execute(
            text("UPDATE resources SET status = 'inactive' WHERE status = 'maintenance'")
        )
