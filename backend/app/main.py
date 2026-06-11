"""FastAPI entrypoint.

Serves the JSON API under /api and, in production, the built React frontend
(static files) for everything else — so the whole app ships as one container
with no external CDN (matches the local-first / no-egress constraint).
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request
from starlette.responses import JSONResponse

from app import __version__
from app.api.applications import router as applications_router

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s"
)
log = logging.getLogger("labelcheck")

app = FastAPI(
    title="label-check",
    version=__version__,
    summary="TTB alcohol label verification — local-first, deterministic compliance.",
)

# In dev the Vite server runs on :5173 and proxies /api here; allow it.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    """Liveness check used by Docker / the deploy platform and the bench harness."""
    return {"status": "ok", "version": __version__}


app.include_router(applications_router)


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error: %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500, content={"detail": "internal error", "path": request.url.path}
    )


# --- Static frontend (only present after the Vite build is copied in) ----------
# Build step 1 wires the plumbing; the directory is populated by the Docker build.
_STATIC_DIR = Path(__file__).parent / "static"

if _STATIC_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=_STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str) -> FileResponse:
        """Serve the SPA index for any non-API route (client-side routing)."""
        if full_path.startswith("api/"):
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="not found")
        index = _STATIC_DIR / "index.html"
        return FileResponse(index)
