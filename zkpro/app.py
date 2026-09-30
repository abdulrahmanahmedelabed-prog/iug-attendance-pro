"""FastAPI application: web UI + REST API + ADMS endpoints + background jobs."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from . import store
from .adms import sync
from .adms.server import router as adms_router
from .api import attendance, devices, personnel, system
from .bootstrap import init_db
from .db import now, session_scope
from .version import APP_NAME, VERSION

log = logging.getLogger("zkpro")
WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def maintenance_tick(state: dict) -> None:
    """Runs every minute: re-queue unanswered commands, BioTime API sync, nightly backup."""
    with session_scope() as db:
        sync.requeue_stale(db)
        hour = int(store.get(db, "backup.hour") or 2)
        keep = int(store.get(db, "backup.keep") or 14)
        bt_on = bool(store.get(db, "biotime.enabled")) and bool(store.get(db, "biotime.url"))
        bt_every = max(1, int(store.get(db, "biotime.interval") or 5))
    if bt_on:
        from . import biotime_push
        try:  # local changes first, so the pull never brings back an older copy
            biotime_push.push_pending()
        except Exception:  # noqa: BLE001
            log.exception("BioTime write-back failed")
    if bt_on and (now().timestamp() - state.get("biotime_at", 0)) >= bt_every * 60:
        state["biotime_at"] = now().timestamp()
        from . import biotime_sync
        try:
            biotime_sync.run_logged()
        except Exception:  # noqa: BLE001 - recorded for the UI by run_logged
            pass
    from . import tcp_pull
    tcp_pull.poll_due(state)
    today = now().date()
    if now().hour == hour and state.get("backup_day") != today:
        from .api.system import make_backup, prune_backups
        try:
            make_backup("auto")
            prune_backups(keep)
            state["backup_day"] = today
        except Exception:
            log.exception("automatic backup failed")


async def _worker():
    state: dict = {}
    while True:
        try:
            await run_in_threadpool(maintenance_tick, state)
        except Exception:
            log.exception("maintenance failed")
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    task = asyncio.create_task(_worker())
    try:
        yield
    finally:
        task.cancel()


def create_app() -> FastAPI:
    app = FastAPI(title=APP_NAME, version=VERSION, lifespan=lifespan, docs_url="/api/docs", redoc_url=None)
    app.include_router(adms_router)
    for r in (system.router, personnel.router, devices.router, attendance.router):
        app.include_router(r)
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/login", include_in_schema=False)
    def login_page():
        return RedirectResponse("/#login")

    return app


app = create_app()
