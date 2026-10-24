"""MolTel — FastAPI application entry point."""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv

# Load .env before anything else (no-op if file does not exist)
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api import compound, dossier, literature, trials

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="MolTel API",
    description="MolTel — research intelligence API over public scientific databases",
    version="1.0.0",
)

# CORS — allow frontend origin(s)
# `FRONTEND_ORIGIN` is a comma-separated list so one deployment can serve a
# production URL and its preview URLs; the browser calls this API directly,
# so an origin left out here simply cannot read results.
_allowed_origins = [
    origin.strip()
    for origin in os.getenv("FRONTEND_ORIGIN", "http://localhost:3000").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers
app.include_router(dossier.router, prefix="/api")
app.include_router(compound.router, prefix="/api")
app.include_router(literature.router, prefix="/api")
app.include_router(trials.router, prefix="/api")


@app.get("/health")
async def health_check() -> dict:
    """Health check endpoint."""
    return {"status": "ok"}


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Top-level exception handler — returns structured error JSON."""
    logger.exception("Unhandled exception on %s %s", request.method, request.url)
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error", "detail": str(exc)},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
