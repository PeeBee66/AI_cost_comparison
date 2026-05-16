from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Model(Base):
    __tablename__ = "models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(40), index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    homepage_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    pricing_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    buy_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    buy_label: Mapped[str | None] = mapped_column(String(60), nullable=True)
    third_party_apis: Mapped[list | None] = mapped_column(JSON, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    discovered: Mapped[bool] = mapped_column(Boolean, default=False)
    quality: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1..5
    tier: Mapped[str | None] = mapped_column(String(40), nullable=True)
    released_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    snapshots: Mapped[list["PriceSnapshot"]] = relationship(
        back_populates="model", cascade="all, delete-orphan"
    )


class PriceSnapshot(Base):
    __tablename__ = "price_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id"), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    source: Mapped[str] = mapped_column(String(40))  # seed | scrape | manual | discovery
    pricing_type: Mapped[str] = mapped_column(String(20))  # api | subscription
    refresh_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("refresh_runs.id"), nullable=True, index=True
    )

    # API pricing (USD; nullable per category)
    input_per_mtok: Mapped[float | None] = mapped_column(Float, nullable=True)
    output_per_mtok: Mapped[float | None] = mapped_column(Float, nullable=True)
    per_image_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    per_5s_video_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    per_minute_video_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    per_song_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Subscription
    subscription_usd_month: Mapped[float | None] = mapped_column(Float, nullable=True)
    subscription_units: Mapped[str | None] = mapped_column(String(200), nullable=True)
    subscription_plan: Mapped[str | None] = mapped_column(String(120), nullable=True)

    raw: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    model: Mapped[Model] = relationship(back_populates="snapshots")
    run: Mapped["RefreshRun | None"] = relationship(back_populates="snapshots")


class RefreshRun(Base):
    __tablename__ = "refresh_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running|success|partial|failed
    discovered_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    snapshots: Mapped[list[PriceSnapshot]] = relationship(back_populates="run")
