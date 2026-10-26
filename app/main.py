"""FastAPI entry point: `uvicorn app.main:app --host 0.0.0.0 --port 8000`."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import router
from app.config.settings import AppSettings, get_settings
from app.services.guardian import Conflict, Guardian, NotFound


def create_app(settings: AppSettings | None = None, guardian: Guardian | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.guardian = guardian or Guardian(settings)
        app.state.guardian.portfolio()  # warm the dashboard cache
        yield

    app = FastAPI(
        title="MAINGAU Guardian API",
        version="1.0.0",
        description="Next Best Action engine that maximises customer lifetime value — and knows when NOT to sell. "
                    "All monetary values are model-based estimates. See API_CONTRACT.md.",
        lifespan=lifespan,
    )
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=False,
                       allow_methods=["GET", "POST", "PUT", "OPTIONS"], allow_headers=["*"])

    @app.exception_handler(NotFound)
    async def _nf(_: Request, exc: NotFound):
        return JSONResponse(status_code=404, content={"error": "not_found", "detail": str(exc)})

    @app.exception_handler(Conflict)
    async def _cf(_: Request, exc: Conflict):
        return JSONResponse(status_code=409, content={"error": "conflict", "detail": str(exc)})

    @app.exception_handler(ValueError)
    async def _ve(_: Request, exc: ValueError):
        return JSONResponse(status_code=422, content={"error": "invalid_request", "detail": str(exc)})

    @app.exception_handler(RequestValidationError)
    async def _rv(_: Request, exc: RequestValidationError):
        errors = [{"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"error": "validation_error", "detail": errors})

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        return JSONResponse(status_code=exc.status_code, content={"error": "http_error", "detail": exc.detail})

    app.include_router(router)
    return app


app = create_app()
