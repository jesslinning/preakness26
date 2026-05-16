"""
FastAPI app: live odds API + optional static serving of the Vite production build.

Run from repository root::

    pip install -r app/requirements.txt
    cd app/web && npm run build && cd ../..
    uvicorn app.odds_api:app --host 0.0.0.0 --port 8000

Environment:

- LIVE_ODDS_REFRESH_SECONDS: background refetch interval (default 120). Set to 0 to disable.
- STATIC_DIST: override path to ``web/dist`` (default: ``app/web/dist`` next to this package).
"""

from __future__ import annotations

import asyncio
import logging
import os
import traceback
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.staticfiles import StaticFiles

from app.live_odds import LIVE_ODDS_URL, fetch_and_parse_preakness_odds

logger = logging.getLogger("odds_api")

_APP_DIR = Path(__file__).resolve().parent
_DEFAULT_DIST = _APP_DIR / "web" / "dist"


def _dist_dir() -> Path:
    raw = os.environ.get("STATIC_DIST", "").strip()
    return Path(raw).resolve() if raw else _DEFAULT_DIST


def _refresh_interval_s() -> float:
    return float(os.environ.get("LIVE_ODDS_REFRESH_SECONDS", "120"))


_cache: dict[str, Any] | None = None
_cache_error: str | None = None
_lock = asyncio.Lock()


async def _fetch_and_store_unlocked() -> None:
    global _cache, _cache_error
    try:
        result = await fetch_and_parse_preakness_odds()
        _cache = {
            "fetched_at": result.fetched_at_iso,
            "source_url": result.source_url,
            "horses": result.horses,
            "error": None,
        }
        _cache_error = None
        logger.info("Live odds refreshed: %d horses", len(result.horses))
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        logger.warning("Live odds fetch failed: %s\n%s", err, traceback.format_exc())
        _cache_error = err
        if _cache is None:
            _cache = {
                "fetched_at": None,
                "source_url": LIVE_ODDS_URL,
                "horses": [],
                "error": err,
            }


async def refresh_live_odds() -> dict[str, Any]:
    """Force a refetch; returns the snapshot dict."""
    async with _lock:
        await _fetch_and_store_unlocked()
        return dict(_cache) if _cache else {}


async def _background_loop() -> None:
    interval = _refresh_interval_s()
    if interval <= 0:
        return
    while True:
        await asyncio.sleep(interval)
        async with _lock:
            await _fetch_and_store_unlocked()


@asynccontextmanager
async def _lifespan(app: FastAPI):
    bg: asyncio.Task | None = None
    async with _lock:
        await _fetch_and_store_unlocked()
    if _refresh_interval_s() > 0:
        bg = asyncio.create_task(_background_loop())
    yield
    if bg:
        bg.cancel()
        try:
            await bg
        except asyncio.CancelledError:
            pass


def create_app() -> FastAPI:
    app = FastAPI(title="Preakness Stakes live odds", version="0.1.0", lifespan=_lifespan)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/live-odds")
    async def get_live_odds() -> JSONResponse:
        async with _lock:
            if _cache is None:
                return JSONResponse(
                    status_code=503,
                    content={
                        "fetched_at": None,
                        "source_url": LIVE_ODDS_URL,
                        "horses": [],
                        "error": _cache_error or "Live odds not yet loaded",
                    },
                )
            return JSONResponse(content=_cache)

    @app.post("/api/live-odds/refresh")
    async def post_refresh() -> JSONResponse:
        body = await refresh_live_odds()
        return JSONResponse(content=body)

    dist = _dist_dir()
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="static")
        logger.info("Serving static files from %s", dist)
    else:
        logger.warning(
            "Static dist not found at %s — API only; build the Vite app to enable UI.",
            dist,
        )

    return app


app = create_app()
