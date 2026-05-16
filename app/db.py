from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import DB_URL

engine = create_engine(
    DB_URL,
    connect_args={"check_same_thread": False},
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


@contextmanager
def session_scope():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    from app import models  # noqa: F401  ensure models are registered

    Base.metadata.create_all(bind=engine)

    # Lazy column additions for older DBs created before these were introduced.
    additions = [
        ("models", "quality", "INTEGER"),
        ("models", "tier", "VARCHAR(40)"),
        ("models", "released_at", "VARCHAR(40)"),
        ("models", "buy_url", "VARCHAR(500)"),
        ("models", "buy_label", "VARCHAR(60)"),
        ("models", "third_party_apis", "JSON"),
    ]
    with engine.begin() as conn:
        for table, col, coltype in additions:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}"))
            except Exception:
                pass  # column already exists
