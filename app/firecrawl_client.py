import logging

import httpx

from app.config import FIRECRAWL_API_KEY, FIRECRAWL_URL

log = logging.getLogger(__name__)


class FirecrawlClient:
    """Thin wrapper over a self-hosted Firecrawl instance.

    The local Firecrawl exposes /v1/scrape returning JSON with `markdown` and `html`.
    """

    def __init__(self, base_url: str = FIRECRAWL_URL, api_key: str = FIRECRAWL_API_KEY):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    async def scrape(self, url: str, timeout: float = 60.0) -> str | None:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "url": url,
            "formats": ["markdown"],
            "onlyMainContent": True,
        }
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/v1/scrape",
                    headers=headers,
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("Firecrawl scrape failed for %s: %s", url, exc)
            return None

        # Firecrawl returns either {data: {markdown: ...}} or {markdown: ...}
        if isinstance(data, dict):
            inner = data.get("data", data)
            md = inner.get("markdown") if isinstance(inner, dict) else None
            if md:
                return md
        log.warning("Firecrawl response missing markdown for %s", url)
        return None
