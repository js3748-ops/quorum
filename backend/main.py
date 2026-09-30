import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from backend.database import init_db
from backend.routes import admin, auth, bookings, dashboard, resources


load_dotenv()

app = FastAPI(
    title="Quorum API",
    description="JSON API for congestion-aware campus resource booking.",
    version="1.0.0",
)


@app.on_event("startup")
def startup():
    init_db()


@app.get("/", include_in_schema=False)
def api_root():
    return RedirectResponse("/docs")


app.include_router(auth.router)
app.include_router(resources.router)
app.include_router(bookings.router)
app.include_router(admin.router)
app.include_router(dashboard.router)
app.include_router(dashboard.user_router)

# Local development only. Production deployments must set SESSION_SECRET.
SESSION_SECRET = os.getenv("SESSION_SECRET") or "local-development-only-change-me"
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    same_site="lax",
    https_only=False,
    max_age=60 * 60 * 24 * 7,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5500", "http://localhost:5500"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
