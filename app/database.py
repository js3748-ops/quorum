from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker


BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "quorum.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    future=True,
)
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
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    request_columns = {column["name"] for column in inspect(engine).get_columns("requests")}
    if "rejection_note" not in request_columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE requests ADD COLUMN rejection_note TEXT"))
    user_columns = {column["name"] for column in inspect(engine).get_columns("users")}
    migrations = {
        "email": "ALTER TABLE users ADD COLUMN email VARCHAR(255)",
        "password_hash": "ALTER TABLE users ADD COLUMN password_hash VARCHAR(64)",
        "password_salt": "ALTER TABLE users ADD COLUMN password_salt VARCHAR(32)",
        "is_demo": "ALTER TABLE users ADD COLUMN is_demo BOOLEAN NOT NULL DEFAULT 0",
    }
    with engine.begin() as connection:
        for column, statement in migrations.items():
            if column not in user_columns:
                connection.execute(text(statement))
        connection.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email ON users (email)")
        )
