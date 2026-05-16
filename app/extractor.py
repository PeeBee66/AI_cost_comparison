"""Use the Claude Code CLI (subscription-backed) to extract structured pricing.

Talks to `claude -p "<prompt>"` via subprocess. No API key required — auth lives
in the claude_auth Docker volume (populated once by running
`docker compose run --rm cost-dashboard claude`).
"""
import json
import logging
import re
import subprocess

from app.config import CLAUDE_BIN

log = logging.getLogger(__name__)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _strip_fences(text: str) -> str:
    m = _JSON_FENCE_RE.search(text)
    return m.group(1).strip() if m else text.strip()


def _run_claude(prompt: str, *, timeout: int = 180) -> str | None:
    try:
        result = subprocess.run(
            [CLAUDE_BIN, "-p", prompt],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        log.warning("claude binary not found at %s; skipping LLM call", CLAUDE_BIN)
        return None
    except subprocess.TimeoutExpired:
        log.warning("claude call timed out after %ss", timeout)
        return None

    if result.returncode != 0:
        log.warning(
            "claude exit %s; stderr: %s",
            result.returncode,
            result.stderr.strip()[:500],
        )
        return None
    return result.stdout


def _parse_json(text: str) -> dict | list | None:
    cleaned = _strip_fences(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # Try to find the first {...} or [...] block as a last resort.
    m = re.search(r"(\{.*\}|\[.*\])", cleaned, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError as e:
            log.warning("Could not parse JSON from claude output: %s", e)
    return None


EXTRACTION_SCHEMA = """
{
  "found": boolean,
  "pricing_type": "api" | "subscription" | "both" | "unknown",
  "input_per_mtok": number | null,        // USD per 1M input tokens
  "output_per_mtok": number | null,       // USD per 1M output tokens
  "per_image_usd": number | null,         // USD per generated image
  "per_5s_video_usd": number | null,      // USD per 5-second video clip
  "per_minute_video_usd": number | null,  // USD per minute of video
  "per_song_usd": number | null,          // USD per generated song
  "subscription_plan": string | null,     // e.g. "Pro", "Plus"
  "subscription_usd_month": number | null,
  "subscription_units": string | null,    // e.g. "200 images/mo"
  "notes": string | null
}
""".strip()


def extract_pricing(model_name: str, category: str, markdown: str) -> dict | None:
    """Send pricing-page markdown to Claude Code and ask for structured pricing."""
    snippet = markdown[:60_000]
    prompt = (
        "You extract pricing information from web pages.\n"
        "If the page does not mention the specific model requested, set found=false.\n"
        "Only report numbers explicitly shown on the page. Do not guess.\n"
        "Respond with ONLY valid JSON — no preamble, no markdown fences, no commentary.\n\n"
        f"Model to find: {model_name}\n"
        f"Category: {category}\n\n"
        f"Schema:\n{EXTRACTION_SCHEMA}\n\n"
        f"Pricing page markdown:\n\n{snippet}\n"
    )

    raw = _run_claude(prompt)
    if not raw:
        return None
    payload = _parse_json(raw)
    if not isinstance(payload, dict):
        return None
    if not payload.get("found"):
        return None
    return payload


DISCOVERY_SCHEMA = """
{
  "models": [
    {
      "provider": string,
      "name": string,
      "slug": string,        // lowercase, "provider/model-name", hyphens not spaces
      "pricing_url": string | null,
      "homepage_url": string | null,
      "notes": string | null
    }
  ]
}
""".strip()


def discover_models(category: str, category_label: str, known_slugs: list[str]) -> list[dict]:
    """Ask Claude Code for current notable models in a category, excluding known ones."""
    known = "\n".join(f"- {s}" for s in known_slugs) or "(none)"
    prompt = (
        f"List the most notable currently-available AI models in the "
        f"'{category_label}' category (internal key: {category}).\n"
        "Only include models that are publicly available and have public pricing.\n"
        "Return at most 8 models.\n"
        "Exclude models I already track:\n\n"
        f"{known}\n\n"
        "Respond with ONLY valid JSON — no preamble, no markdown fences, no commentary.\n\n"
        f"Schema:\n{DISCOVERY_SCHEMA}\n"
    )

    raw = _run_claude(prompt, timeout=240)
    if not raw:
        return []
    payload = _parse_json(raw)
    if isinstance(payload, dict):
        models = payload.get("models", [])
    elif isinstance(payload, list):
        models = payload
    else:
        models = []
    return [m for m in models if isinstance(m, dict) and m.get("slug")]
