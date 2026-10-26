"""Lighty — Smarter decisions. Better conversations.

FastAPI entry point: `uvicorn app.main:app --host 0.0.0.0 --port 8000`.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.copilot_routes import router as copilot_router
from app.api.routes import router
from app.config.settings import AppSettings, get_settings
from app.services.access_control import Forbidden, Unauthorized
from app.services.employee_copilot_service import CopilotUnavailable
from app.services.lighty import Conflict, Lighty, NotFound

APP_NAME = "Lighty"
TAGLINE = "Smarter decisions. Better conversations."
API_VERSION = "1.1.0"

DESCRIPTION = (
    f"**{TAGLINE}**\n\n"
    "Lighty is MAINGAU Energie's Next Best Action engine and internal employee copilot. The engine maximises "
    "customer lifetime value and knows when NOT to sell; the copilot gives service and sales staff grounded, "
    "personalised guidance from the customer database. It never contacts customers and every customer-facing text "
    "needs human approval. All monetary values are model-based estimates. See API_CONTRACT.md."
)


def create_app(settings: AppSettings | None = None, lighty: Lighty | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.lighty = lighty or Lighty(settings)
        if settings.warm_portfolio_on_startup:
            app.state.lighty.portfolio()  # warm the dashboard cache
        logging.getLogger("lighty").info("%s ready: %s", APP_NAME, TAGLINE)
        yield

    app = FastAPI(title=f"{APP_NAME} API", version=API_VERSION, summary=TAGLINE, description=DESCRIPTION,
                  lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=False,
                       allow_methods=["GET", "POST", "PUT", "OPTIONS"], allow_headers=["*"])

    def err(status: int, code: str, detail):
        return JSONResponse(status_code=status, content={"error": code, "detail": detail})

    @app.exception_handler(NotFound)
    async def _nf(_: Request, exc: NotFound):
        return err(404, "not_found", str(exc))

    @app.exception_handler(Conflict)
    async def _cf(_: Request, exc: Conflict):
        return err(409, "conflict", str(exc))

    @app.exception_handler(Unauthorized)
    async def _ua(_: Request, exc: Unauthorized):
        return err(401, "unauthorized", str(exc))

    @app.exception_handler(Forbidden)
    async def _fb(_: Request, exc: Forbidden):
        return err(403, "forbidden", str(exc))

    @app.exception_handler(CopilotUnavailable)
    async def _cu(_: Request, exc: CopilotUnavailable):
        return err(503, "ai_unavailable", str(exc))

    @app.exception_handler(ValueError)
    async def _ve(_: Request, exc: ValueError):
        return err(422, "invalid_request", str(exc))

    @app.exception_handler(RequestValidationError)
    async def _rv(_: Request, exc: RequestValidationError):
        errors = [{"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return err(422, "validation_error", errors)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        return err(exc.status_code, "http_error", exc.detail)

    app.include_router(router)
    app.include_router(copilot_router)
    return app


app = create_app()
