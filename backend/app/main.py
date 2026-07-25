"""FastAPI application entrypoint — Toplantı Tutanağı (Faz 1)."""
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import create_tables
from .routers import meetings

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_tables()
    yield


app = FastAPI(title="Toplantı Tutanağı API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    # Local dev/testing: any localhost/127.0.0.1 port.
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "X-Edit-Token"],
)

app.include_router(meetings.router)


@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok", "server_time": datetime.now(timezone.utc)}
