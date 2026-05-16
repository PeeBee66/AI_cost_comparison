import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
(DATA_DIR / "backups").mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "cost_dashboard.db"
DB_URL = f"sqlite:///{DB_PATH}"

APP_PORT = int(os.getenv("APP_PORT", "8556"))

CLAUDE_BIN = os.getenv("CLAUDE_BIN", "claude")

FIRECRAWL_URL = os.getenv("FIRECRAWL_URL", "http://firecrawl:3002").rstrip("/")
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "")

ENABLE_DISCOVERY = os.getenv("ENABLE_DISCOVERY", "1") == "1"

ENABLE_NIGHTLY = os.getenv("ENABLE_NIGHTLY", "1") == "1"
NIGHTLY_HOUR_UTC = int(os.getenv("NIGHTLY_HOUR_UTC", "3"))
NIGHTLY_MINUTE_UTC = int(os.getenv("NIGHTLY_MINUTE_UTC", "0"))

SEED_PATH = Path(__file__).parent / "prices_seed.yaml"

CATEGORIES = {
    "chat": {
        "label": "Chat / Code",
        "unit": "per 1M output tokens",
        "metric_field": "output_per_mtok",
    },
    "image": {
        "label": "Image Generation",
        "unit": "per image",
        "metric_field": "per_image_usd",
    },
    "video_short": {
        "label": "Video (≤5 sec)",
        "unit": "per 5 sec clip",
        "metric_field": "per_5s_video_usd",
    },
    "video_long": {
        "label": "Video (≥1 min)",
        "unit": "per minute",
        "metric_field": "per_minute_video_usd",
    },
    "music": {
        "label": "Music Generation",
        "unit": "per song",
        "metric_field": "per_song_usd",
    },
}
