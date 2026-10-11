"""AirWindow API (FastAPI). Runs under uvicorn locally and Mangum on Lambda."""

from __future__ import annotations

import json
import logging
import time
from datetime import date
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from .errors import ProviderError
from .planner import PlanInputError
from .routes_campus import make_router
from .runtime import Runtime, build

log = logging.getLogger("airwindow")
logging.basicConfig(level=logging.INFO)

_STATUS = {"rate_limited": 503, "not_captured": 404, "not_configured": 503}


def Lat():
    return Query(..., ge=-90, le=90)


def Lon(wrap: bool = False):
    # Map bounds may extend past ±180° when the user pans across the antimeridian.
    return Query(..., ge=-540, le=540) if wrap else Query(..., ge=-180, le=180)


class PlanRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    tz: str | None = Field(None, max_length=64)
    day: str
    allowed_start: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    allowed_end: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    duration_min: int = Field(..., ge=15, le=480)
    baseline_start: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    threshold_aqi: int = Field(100, ge=0, le=500)

    @field_validator("day")
    @classmethod
    def _day(cls, v: str) -> str:
        date.fromisoformat(v)
        return v


def create_app(rt: Runtime) -> FastAPI:
    service = rt.service
    settings = rt.settings
    app = FastAPI(title="AirWindow API", version="0.2.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.rt = rt
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Content-Type", "Authorization"],
        )

    @app.middleware("http")
    async def access_log(request: Request, call_next):
        t0 = time.perf_counter()
        resp = await call_next(request)
        if request.url.path.startswith("/api/"):
            resp.headers.setdefault("Cache-Control", "no-store")
            # Structured access log (CloudWatch Logs on AWS). No query strings: they may contain coordinates.
            log.info(json.dumps({"evt": "request", "method": request.method, "path": request.url.path,
                                 "status": resp.status_code, "ms": round((time.perf_counter() - t0) * 1000)}))
        return resp

    @app.exception_handler(ProviderError)
    async def provider_error(_: Request, err: ProviderError):
        log.warning("provider error: %s", err)
        return JSONResponse(
            status_code=_STATUS.get(err.kind, 502),
            content={"error": err.as_dict(), "mode": service.mode,
                     "message": "No data is shown rather than substituting simulated values."},
        )

    @app.exception_handler(PlanInputError)
    async def plan_error(_: Request, err: PlanInputError):
        return JSONResponse(status_code=400, content={"error": {"kind": "invalid_input", "message": str(err)}})

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return service.health()

    @app.get("/api/geocode")
    async def geocode(q: str = Query(..., min_length=2, max_length=80)) -> dict[str, Any]:
        return await service.geocode(q)

    @app.get("/api/point")
    async def point(lat: float = Lat(), lon: float = Lon(), tz: str | None = Query(None, max_length=64)):
        return await service.point(lat, lon, tz)

    @app.get("/api/grid")
    async def grid(south: float = Lat(), west: float = Lon(True), north: float = Lat(), east: float = Lon(True)):
        return await service.grid(south, west, north, east)

    @app.get("/api/stations")
    async def stations(lat: float = Lat(), lon: float = Lon(), radius_km: float = Query(25, gt=0, le=25)):
        return await service.stations(lat, lon, radius_km)

    @app.post("/api/plan")
    async def plan(req: PlanRequest):
        return await service.plan(req.model_dump())

    app.include_router(make_router(rt))

    if settings.static_dir and settings.static_dir.is_dir():
        # Optional: serve a built frontend from the same process for local previews.
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="static")
    return app


runtime = build()
app = create_app(runtime)
service = runtime.service

from mangum import Mangum  # noqa: E402


def make_lambda_handler(fastapi_app: FastAPI):
    """Wrap an app for Lambda. Mangum runs each request on the thread's current
    event loop; make sure one exists and is open (warm containers reuse it)."""
    mangum = Mangum(fastapi_app, lifespan="off")

    def _handler(event, context):
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                raise RuntimeError("closed")
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())
        return mangum(event, context)

    return _handler


handler = make_lambda_handler(app)
