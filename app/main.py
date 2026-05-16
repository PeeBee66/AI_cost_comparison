import asyncio
import logging
import shutil
from datetime import datetime
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, select

from app.config import (
    CATEGORIES,
    DATA_DIR,
    DB_PATH,
    ENABLE_NIGHTLY,
    NIGHTLY_HOUR_UTC,
    NIGHTLY_MINUTE_UTC,
)
from app.db import init_db, session_scope
from app.models import Model, PriceSnapshot, RefreshRun
from app.refresh import run_refresh
from app.scheduler import nightly_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("cost_dashboard")

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="Cost Dashboard", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

_refresh_lock = asyncio.Lock()
_nightly_task: asyncio.Task | None = None


@app.on_event("startup")
async def on_startup() -> None:
    global _nightly_task
    init_db()
    # Always run a seed-only refresh on boot so YAML edits propagate
    # (adds new models, updates quality/tier/notes; idempotent via slug upsert).
    log.info("Running boot seed refresh")
    try:
        await run_refresh(do_scrape=False, do_discovery=False)
    except Exception:
        log.exception("Boot seed failed")

    _nightly_task = asyncio.create_task(nightly_loop(run_refresh, _refresh_lock))


@app.on_event("shutdown")
async def on_shutdown() -> None:
    if _nightly_task and not _nightly_task.done():
        _nightly_task.cancel()
        try:
            await _nightly_task
        except (asyncio.CancelledError, Exception):
            pass


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}


def _latest_snapshots_by_model() -> dict[int, dict[str, PriceSnapshot]]:
    """Map model_id -> {'api': snapshot, 'subscription': snapshot} (most recent)."""
    out: dict[int, dict[str, PriceSnapshot]] = {}
    with session_scope() as session:
        snaps = session.scalars(
            select(PriceSnapshot).order_by(desc(PriceSnapshot.captured_at))
        ).all()
        for s in snaps:
            bucket = out.setdefault(s.model_id, {})
            if s.pricing_type not in bucket:
                bucket[s.pricing_type] = s
        # detach all
        session.expunge_all()
    return out


def _build_view() -> dict:
    """Assemble the data structure the index template renders."""
    latest = _latest_snapshots_by_model()
    sections: dict[str, dict] = {}
    with session_scope() as session:
        models = session.scalars(
            select(Model).where(Model.active.is_(True)).order_by(Model.provider, Model.name)
        ).all()
        for m in models:
            cat = m.category
            meta = CATEGORIES.get(cat)
            if not meta:
                continue
            row = {
                "id": m.id,
                "slug": m.slug,
                "provider": m.provider,
                "name": m.name,
                "notes": m.notes,
                "pricing_url": m.pricing_url,
                "buy_url": m.buy_url or m.pricing_url,
                "buy_label": m.buy_label or "Buy / sign up",
                "third_party_apis": m.third_party_apis or [],
                "homepage_url": m.homepage_url,
                "discovered": m.discovered,
                "quality": m.quality,
                "tier": m.tier,
                "released_at": m.released_at,
                "api": None,
                "subscription": None,
                "metric": None,
            }
            snaps = latest.get(m.id, {})
            if "api" in snaps:
                api_snap = snaps["api"]
                row["api"] = {
                    "captured_at": api_snap.captured_at,
                    "source": api_snap.source,
                    "input_per_mtok": api_snap.input_per_mtok,
                    "output_per_mtok": api_snap.output_per_mtok,
                    "per_image_usd": api_snap.per_image_usd,
                    "per_5s_video_usd": api_snap.per_5s_video_usd,
                    "per_minute_video_usd": api_snap.per_minute_video_usd,
                    "per_song_usd": api_snap.per_song_usd,
                }
                metric_value = getattr(api_snap, meta["metric_field"], None)
                if metric_value is not None:
                    row["metric"] = metric_value
            if "subscription" in snaps:
                sub_snap = snaps["subscription"]
                row["subscription"] = {
                    "captured_at": sub_snap.captured_at,
                    "source": sub_snap.source,
                    "plan": sub_snap.subscription_plan,
                    "usd_month": sub_snap.subscription_usd_month,
                    "units": sub_snap.subscription_units,
                }
            section = sections.setdefault(
                cat,
                {
                    "key": cat,
                    "label": meta["label"],
                    "unit": meta["unit"],
                    "rows": [],
                    "cheapest_api_id": None,
                    "cheapest_sub_id": None,
                },
            )
            section["rows"].append(row)

    # determine "cheapest" per section
    for sec in sections.values():
        api_candidates = [
            r for r in sec["rows"] if r["metric"] is not None
        ]
        if api_candidates:
            cheapest = min(api_candidates, key=lambda r: r["metric"])
            sec["cheapest_api_id"] = cheapest["id"]
        sub_candidates = [
            r
            for r in sec["rows"]
            if r["subscription"] and r["subscription"].get("usd_month") is not None
        ]
        if sub_candidates:
            cheapest = min(sub_candidates, key=lambda r: r["subscription"]["usd_month"])
            sec["cheapest_sub_id"] = cheapest["id"]

    # stable order
    ordered = [sections[k] for k in CATEGORIES if k in sections]
    return {"sections": ordered}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    view = _build_view()
    with session_scope() as session:
        last_run = session.scalar(
            select(RefreshRun).order_by(desc(RefreshRun.started_at)).limit(1)
        )
        last_run_info = None
        if last_run:
            last_run_info = {
                "id": last_run.id,
                "started_at": last_run.started_at,
                "finished_at": last_run.finished_at,
                "status": last_run.status,
                "discovered_count": last_run.discovered_count,
                "updated_count": last_run.updated_count,
                "notes": last_run.notes,
            }
    next_nightly = None
    if ENABLE_NIGHTLY:
        from app.scheduler import _seconds_until_next

        secs = _seconds_until_next(NIGHTLY_HOUR_UTC, NIGHTLY_MINUTE_UTC)
        next_nightly = {
            "hour": NIGHTLY_HOUR_UTC,
            "minute": NIGHTLY_MINUTE_UTC,
            "in_hours": round(secs / 3600, 1),
        }
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "sections": view["sections"],
            "last_run": last_run_info,
            "refreshing": _refresh_lock.locked(),
            "next_nightly": next_nightly,
        },
    )


@app.get("/model/{model_id}/history", response_class=HTMLResponse)
async def model_history(request: Request, model_id: int) -> HTMLResponse:
    with session_scope() as session:
        model = session.get(Model, model_id)
        if not model:
            raise HTTPException(status_code=404, detail="Model not found")
        snaps = session.scalars(
            select(PriceSnapshot)
            .where(PriceSnapshot.model_id == model_id)
            .order_by(desc(PriceSnapshot.captured_at))
        ).all()
        snap_dicts = [
            {
                "captured_at": s.captured_at,
                "source": s.source,
                "pricing_type": s.pricing_type,
                "input_per_mtok": s.input_per_mtok,
                "output_per_mtok": s.output_per_mtok,
                "per_image_usd": s.per_image_usd,
                "per_5s_video_usd": s.per_5s_video_usd,
                "per_minute_video_usd": s.per_minute_video_usd,
                "per_song_usd": s.per_song_usd,
                "subscription_plan": s.subscription_plan,
                "subscription_usd_month": s.subscription_usd_month,
                "subscription_units": s.subscription_units,
            }
            for s in snaps
        ]
        model_view = {
            "id": model.id,
            "name": model.name,
            "provider": model.provider,
            "category": model.category,
            "pricing_url": model.pricing_url,
        }
    return templates.TemplateResponse(
        "history.html",
        {"request": request, "model": model_view, "snapshots": snap_dicts},
    )


@app.post("/refresh")
async def trigger_refresh(background: BackgroundTasks, scrape: bool = True, discover: bool = True):
    if _refresh_lock.locked():
        return JSONResponse(
            {"ok": False, "message": "Refresh already running"}, status_code=409
        )

    async def _job():
        async with _refresh_lock:
            try:
                await run_refresh(do_scrape=scrape, do_discovery=discover)
            except Exception:
                log.exception("Refresh job failed")

    background.add_task(_job)
    return RedirectResponse(url="/", status_code=303)


@app.get("/api/status")
async def status() -> dict:
    with session_scope() as session:
        last_run = session.scalar(
            select(RefreshRun).order_by(desc(RefreshRun.started_at)).limit(1)
        )
        info = None
        if last_run:
            info = {
                "id": last_run.id,
                "status": last_run.status,
                "started_at": last_run.started_at.isoformat() if last_run.started_at else None,
                "finished_at": last_run.finished_at.isoformat()
                if last_run.finished_at
                else None,
                "discovered_count": last_run.discovered_count,
                "updated_count": last_run.updated_count,
            }
    return {"refreshing": _refresh_lock.locked(), "last_run": info}


@app.post("/backup")
async def backup_now() -> dict:
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    target = DATA_DIR / "backups" / f"cost_dashboard-{ts}.db"
    if not DB_PATH.exists():
        raise HTTPException(status_code=404, detail="DB not found")
    shutil.copy2(DB_PATH, target)
    return {"ok": True, "path": str(target)}
