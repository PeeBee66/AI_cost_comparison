"""Orchestrate a refresh run: seed -> scrape -> extract -> discover -> snapshot."""
import asyncio
import logging
from datetime import datetime
from pathlib import Path

import yaml
from sqlalchemy import select

from app.config import CATEGORIES, ENABLE_DISCOVERY, SEED_PATH
from app.db import session_scope
from app.extractor import discover_models, extract_pricing
from app.firecrawl_client import FirecrawlClient
from app.models import Model, PriceSnapshot, RefreshRun

log = logging.getLogger(__name__)


def _load_seed() -> list[dict]:
    if not Path(SEED_PATH).exists():
        return []
    with open(SEED_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("models", [])


def _upsert_model(session, entry: dict, *, discovered: bool = False) -> Model:
    slug = entry["slug"]
    model = session.scalar(select(Model).where(Model.slug == slug))
    if model is None:
        model = Model(
            slug=slug,
            provider=entry.get("provider", ""),
            name=entry.get("name", slug),
            category=entry["category"],
            notes=entry.get("notes"),
            homepage_url=entry.get("homepage_url"),
            pricing_url=entry.get("pricing_url"),
            buy_url=entry.get("buy_url"),
            buy_label=entry.get("buy_label"),
            third_party_apis=entry.get("third_party_apis"),
            discovered=discovered,
            quality=entry.get("quality"),
            tier=entry.get("tier"),
            released_at=entry.get("released_at"),
        )
        session.add(model)
        session.flush()
    else:
        model.provider = entry.get("provider", model.provider)
        model.name = entry.get("name", model.name)
        model.category = entry.get("category", model.category)
        model.notes = entry.get("notes", model.notes)
        model.homepage_url = entry.get("homepage_url", model.homepage_url)
        model.pricing_url = entry.get("pricing_url", model.pricing_url)
        if entry.get("buy_url") is not None:
            model.buy_url = entry.get("buy_url")
        if entry.get("buy_label") is not None:
            model.buy_label = entry.get("buy_label")
        # third_party_apis: replace whole list when present in YAML
        if "third_party_apis" in entry:
            model.third_party_apis = entry.get("third_party_apis")
        if entry.get("quality") is not None:
            model.quality = entry.get("quality")
        if entry.get("tier") is not None:
            model.tier = entry.get("tier")
        if entry.get("released_at") is not None:
            model.released_at = entry.get("released_at")
    return model


def _snapshot_from_seed(session, model: Model, entry: dict, run: RefreshRun) -> int:
    """Insert snapshot(s) from seed YAML. Returns number of snapshots created."""
    created = 0
    api = entry.get("api")
    if api:
        session.add(
            PriceSnapshot(
                model_id=model.id,
                refresh_run_id=run.id,
                source="seed",
                pricing_type="api",
                input_per_mtok=api.get("input_per_mtok"),
                output_per_mtok=api.get("output_per_mtok"),
                per_image_usd=api.get("per_image_usd"),
                per_5s_video_usd=api.get("per_5s_video_usd"),
                per_minute_video_usd=api.get("per_minute_video_usd"),
                per_song_usd=api.get("per_song_usd"),
                raw=api,
            )
        )
        created += 1
    sub = entry.get("subscription")
    if sub:
        session.add(
            PriceSnapshot(
                model_id=model.id,
                refresh_run_id=run.id,
                source="seed",
                pricing_type="subscription",
                subscription_plan=sub.get("plan"),
                subscription_usd_month=sub.get("usd_month"),
                subscription_units=sub.get("units"),
                raw=sub,
            )
        )
        created += 1
    return created


def _snapshot_from_extraction(
    session, model: Model, payload: dict, run: RefreshRun
) -> int:
    created = 0
    pt = payload.get("pricing_type", "unknown")
    if pt in ("api", "both"):
        session.add(
            PriceSnapshot(
                model_id=model.id,
                refresh_run_id=run.id,
                source="scrape",
                pricing_type="api",
                input_per_mtok=payload.get("input_per_mtok"),
                output_per_mtok=payload.get("output_per_mtok"),
                per_image_usd=payload.get("per_image_usd"),
                per_5s_video_usd=payload.get("per_5s_video_usd"),
                per_minute_video_usd=payload.get("per_minute_video_usd"),
                per_song_usd=payload.get("per_song_usd"),
                raw=payload,
            )
        )
        created += 1
    if pt in ("subscription", "both"):
        session.add(
            PriceSnapshot(
                model_id=model.id,
                refresh_run_id=run.id,
                source="scrape",
                pricing_type="subscription",
                subscription_plan=payload.get("subscription_plan"),
                subscription_usd_month=payload.get("subscription_usd_month"),
                subscription_units=payload.get("subscription_units"),
                raw=payload,
            )
        )
        created += 1
    return created


async def _scrape_and_extract(model: Model) -> dict | None:
    if not model.pricing_url:
        return None
    fc = FirecrawlClient()
    md = await fc.scrape(model.pricing_url)
    if not md:
        return None
    # Claude SDK call is sync; run in thread so we don't block.
    return await asyncio.to_thread(
        extract_pricing, model.name, model.category, md
    )


async def run_refresh(*, do_scrape: bool = True, do_discovery: bool = True) -> int:
    """Execute a refresh. Returns the RefreshRun id."""
    with session_scope() as session:
        run = RefreshRun(status="running", started_at=datetime.utcnow())
        session.add(run)
        session.flush()
        run_id = run.id

    log.info("Starting refresh run %s", run_id)

    # Phase 1: seed
    seed_entries = _load_seed()
    seed_created = 0
    with session_scope() as session:
        run = session.get(RefreshRun, run_id)
        for entry in seed_entries:
            model = _upsert_model(session, entry)
            seed_created += _snapshot_from_seed(session, model, entry, run)
        run.updated_count = seed_created

    # Phase 2: scrape + LLM extract (best-effort, skip on failure)
    scrape_created = 0
    if do_scrape:
        with session_scope() as session:
            models_with_urls = session.scalars(
                select(Model).where(Model.pricing_url.isnot(None))
            ).all()
            model_ids = [(m.id, m.name) for m in models_with_urls]

        for model_id, model_name in model_ids:
            try:
                with session_scope() as session:
                    model = session.get(Model, model_id)
                    payload = await _scrape_and_extract(model)
                    if payload:
                        run = session.get(RefreshRun, run_id)
                        scrape_created += _snapshot_from_extraction(
                            session, model, payload, run
                        )
                        log.info("Scraped pricing for %s", model_name)
            except Exception as exc:  # noqa: BLE001
                log.exception("Scrape failed for %s: %s", model_name, exc)

    # Phase 3: LLM discovery (find new models we don't know about)
    discovered_total = 0
    if do_discovery and ENABLE_DISCOVERY:
        for cat_key, meta in CATEGORIES.items():
            with session_scope() as session:
                known = [
                    s
                    for (s,) in session.execute(
                        select(Model.slug).where(Model.category == cat_key)
                    )
                ]
            try:
                found = await asyncio.to_thread(
                    discover_models, cat_key, meta["label"], known
                )
            except Exception as exc:  # noqa: BLE001
                log.exception("Discovery failed for %s: %s", cat_key, exc)
                found = []

            for m in found:
                slug = m.get("slug", "").strip().lower()
                if not slug or slug in known:
                    continue
                with session_scope() as session:
                    existing = session.scalar(select(Model).where(Model.slug == slug))
                    if existing:
                        continue
                    entry = {
                        "slug": slug,
                        "provider": m.get("provider", ""),
                        "name": m.get("name", slug),
                        "category": cat_key,
                        "notes": m.get("notes"),
                        "pricing_url": m.get("pricing_url"),
                        "homepage_url": m.get("homepage_url"),
                    }
                    _upsert_model(session, entry, discovered=True)
                    discovered_total += 1
                    log.info("Discovered new model: %s", slug)

    # Finalize
    with session_scope() as session:
        run = session.get(RefreshRun, run_id)
        run.finished_at = datetime.utcnow()
        run.status = "success"
        run.discovered_count = discovered_total
        run.updated_count = seed_created + scrape_created
        run.notes = (
            f"seed snapshots: {seed_created}, scrape snapshots: {scrape_created}, "
            f"discovered: {discovered_total}"
        )

    log.info("Refresh run %s finished", run_id)
    return run_id
