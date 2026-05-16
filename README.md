# AI Cost Comparison

A self-hosted dashboard that tracks the price of ~100 commercial AI models — chat / code, image, video (short and long), music — side-by-side, with **API pricing vs subscription pricing**, **quality ratings**, and **third-party API wrappers** (fal.ai, Replicate, PiAPI, etc.) called out separately from official endpoints.

Runs in a single Docker container on port `8556`. Uses **Claude Code CLI** (your existing Claude Pro / Max subscription — no API key) to extract live pricing from each provider's pricing page via a self-hosted **Firecrawl** instance.

---

## Why

Pricing pages move constantly. Across ~100 models from ~40 providers, manually maintaining a comparison spreadsheet is a losing battle. This project:

- Keeps a manual YAML file (`app/prices_seed.yaml`) as the source of truth for what to track.
- Runs a refresh that scrapes each pricing page with Firecrawl, sends the markdown to Claude, and updates the database with structured numbers.
- Surfaces **subscription-only** products clearly (Suno, Midjourney, Udio, Higgsfield…) and lists the third-party API wrappers that exist for each — flagged as either **partner hosts** (fal.ai, Replicate) or **reverse-engineered wrappers** (PiAPI, GoAPI, SunoAPI.com).
- Keeps full price history per model — every refresh inserts a new snapshot row, nothing is destroyed.

---

## Features

- 5 sections: **Chat / Code · Image · Video (≤5 sec) · Video (≥1 min) · Music**
- Each row shows: model name, provider, **1-5 ★ quality rating**, **tier badge** (Frontier / Strong / Value / Niche / Legacy), notes, API price (when applicable), subscription price (when applicable), and a labelled `buy ↗` link pointing at the actual purchase / API-console page.
- **Cheapest highlighting** per section, normalised per category ($/Mtok output for chat, $/image, $/5s clip, $/min, $/song).
- **Third-party API chips** appear under each row when relevant:
  - 🟢 **partner API** — fal.ai, Replicate, BytePlus — legitimate paid relays of the official model.
  - 🟠 **wrapper API ⚠** — PiAPI, GoAPI, SunoAPI.com, ImagineAPI, ApiFrame — reverse-engineered, ToS-grey.
- **Refresh button** runs three phases:
  1. Reload `prices_seed.yaml` and upsert (your edits propagate without wiping the DB).
  2. For each model with a `pricing_url`, fetch via Firecrawl → send markdown to Claude → write a fresh `scrape` snapshot.
  3. Discovery: ask Claude to list current notable models in each category and flag any unknown ones with a purple `NEW` badge.
- **Nightly auto-refresh** (default 03:00 UTC) via a tiny asyncio loop — no external scheduler dependency.
- **Per-model history page** — click any model name to see every snapshot ever recorded.
- **Backup button** snapshots the SQLite DB into `data/backups/` (host-bind-mounted).

---

## Stack

- **Backend**: Python 3.12, FastAPI, SQLAlchemy 2.0, SQLite
- **Frontend**: Jinja2 templates, Tailwind via CDN, vanilla JS (no build step)
- **Scraping**: self-hosted [Firecrawl](https://github.com/mendableai/firecrawl) → returns clean markdown
- **Extraction**: [Claude Code CLI](https://github.com/anthropics/claude-code) (`claude -p "..."`) — uses your Claude.ai subscription, no Anthropic API key required
- **Container**: Docker + Docker Compose

---

## Quick start

> **Prerequisites**: [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows / macOS) or Docker Engine + Compose v2 (Linux). On Windows, run the commands below in **PowerShell** or **Git Bash**.

### 1. Clone + configure

**Linux / macOS / Git Bash:**
```bash
git clone https://github.com/PeeBee66/AI_cost_comparison.git
cd AI_cost_comparison
cp .env.example .env
# edit .env — at minimum point FIRECRAWL_URL at your Firecrawl instance
```

**Windows PowerShell:**
```powershell
git clone https://github.com/PeeBee66/AI_cost_comparison.git
cd AI_cost_comparison
Copy-Item .env.example .env
notepad .env   # set FIRECRAWL_URL
```

### 2. Build the image

```bash
docker compose build
```

### 3. One-time Claude login (inside the container)

The container has `claude` CLI baked in. Log in once — auth is stored in a named Docker volume (`claude_auth`) so it survives rebuilds.

```bash
docker compose run --rm cost-dashboard claude
# follow the URL prompt, log in with your Claude Pro / Max account,
# paste the code back into the terminal, then Ctrl+C when you see the welcome screen
```

Verify:
```bash
docker compose run --rm cost-dashboard claude -p "say hi"
```
If that prints a greeting, you're set.

### 4. Run

```bash
docker compose up -d
```

Open **http://localhost:8556**. The dashboard seeds itself on first boot from `app/prices_seed.yaml` (~100 models pre-configured).

---

## Configuration (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `FIRECRAWL_URL` | `http://firecrawl:3002` | Base URL of your Firecrawl instance |
| `FIRECRAWL_API_KEY` | *(empty)* | Optional, if your Firecrawl needs auth |
| `DATA_DIR` | `/app/data` | Where SQLite + backups live (bind-mounted) |
| `APP_PORT` | `8556` | Internal listen port |
| `CLAUDE_BIN` | `claude` | Path to claude CLI inside the container |
| `ENABLE_DISCOVERY` | `1` | Set `0` to skip the LLM model-discovery phase |
| `ENABLE_NIGHTLY` | `1` | Set `0` to disable the nightly auto-refresh |
| `NIGHTLY_HOUR_UTC` | `3` | Hour (UTC) for nightly refresh |
| `NIGHTLY_MINUTE_UTC` | `0` | Minute |

---

## Editing the model list

`app/prices_seed.yaml` is the source of truth. Add or update an entry, then restart the container — the boot-seed step upserts by `slug` and the changes show up on the next page load.

Entry shape:

```yaml
- slug: anthropic/claude-opus-4-7      # unique key
  provider: Anthropic
  name: Claude Opus 4.7
  category: chat                       # chat | image | video_short | video_long | music
  quality: 5                           # 1..5
  tier: Frontier                       # Frontier | Strong | Value | Niche | Legacy
  released_at: 2026-Q1
  pricing_url: https://www.anthropic.com/pricing
  buy_url: https://console.anthropic.com/settings/billing
  buy_label: API console               # text on the prominent buy chip
  notes: Flagship reasoning, 1M context
  api:                                 # all fields nullable
    input_per_mtok: 15.00
    output_per_mtok: 75.00
  subscription:
    plan: Claude Max
    usd_month: 100.00
    units: Heavy usage, no API cost
  third_party_apis:                    # optional list
    - { provider: fal.ai Veo 3, url: https://fal.ai/...,  per_5s_video_usd: 2.00, kind: partner, notes: "Hosted relay" }
    - { provider: PiAPI Sora,   url: https://piapi.ai/..., per_5s_video_usd: 0.60, kind: wrapper, notes: "Account-pool wrapper" }
```

Category-specific price fields:

| Category | Field |
|---|---|
| `chat` | `input_per_mtok`, `output_per_mtok` |
| `image` | `per_image_usd` |
| `video_short` | `per_5s_video_usd` |
| `video_long` | `per_minute_video_usd` |
| `music` | `per_song_usd` |

---

## How the refresh works

1. **Seed phase** — read `app/prices_seed.yaml`, upsert each model + snapshot. Always runs on boot.
2. **Scrape phase** — for each model with a `pricing_url`, hit Firecrawl `POST /v1/scrape` to get clean markdown, then send it to `claude -p` with a structured-JSON prompt. If Claude reports `found: false`, skip (no fake data is written). Otherwise insert a `scrape` snapshot.
3. **Discovery phase** — for each category, ask Claude to list current notable models. Anything whose slug we don't already track is inserted as a new model with a purple `NEW` badge.

A "refresh run" row is written for each invocation so you can see what changed and when. The history table preserves every snapshot ever taken — `pricing_url`, click the model name to see it.

---

## Routes

| Path | Description |
|---|---|
| `GET /` | Main dashboard |
| `GET /model/{id}/history` | Per-model snapshot history |
| `POST /refresh` | Trigger a refresh run |
| `POST /backup` | Snapshot the SQLite DB into `data/backups/` |
| `GET /api/status` | JSON status of the current refresh |
| `GET /healthz` | Health check (used by Docker) |

---

## Deploying to a remote host

A `deploy.sh` is included. It rsyncs the project (via tar-over-ssh) to a remote, runs `docker compose up -d --build`, and waits for `/healthz`.

```bash
SSH_HOST=you@your.host ./deploy.sh
# or, if you've configured a host alias in ~/.ssh/config:
SSH_HOST=my-server ./deploy.sh
```

Optional overrides:
- `REMOTE_DIR` — defaults to `/srv/cost-dashboard`
- `APP_PORT` — defaults to `8556`

Key selection is handled by your ssh-agent or `~/.ssh/config`. No key path env var is needed.

---

## Backups

The `data/` directory is bind-mounted from the host. The SQLite DB lives at `data/cost_dashboard.db`. To snapshot:

- **From the UI** — "Backup DB" button.
- **Via API** — `curl -X POST http://localhost:8556/backup`
- **Cron** — point a host cron at `scripts/backup.sh`. Keeps the last 30 snapshots, rotates older ones.

---

## Limitations / known gaps

- **No auth.** This is meant for a private LAN. Add a reverse proxy with basic auth if you expose it.
- **Pricing accuracy depends on the providers' pricing pages.** When a provider redesigns their page, extraction quality drops until Claude figures out the new layout. The seed YAML is the fallback.
- **Wrapper-API prices move fast.** Many of the third-party wrappers (PiAPI, GoAPI, etc.) hide pricing behind a signup. The numbers in the seed file are best-effort and should be re-checked before relying on them.
- **Discovery hallucinations are possible.** Claude occasionally invents plausible-sounding model names; the `NEW` badge is a hint to verify, not a guarantee.
- **Container runs as root.** Fine for a homelab; for shared infra, run with a non-root UID and adjust the `claude_auth` volume permissions.

---

## License

GPL-3.0 — see [LICENSE](LICENSE).

---

## Acknowledgements

- [Firecrawl](https://github.com/mendableai/firecrawl) — scraping engine
- [Claude Code](https://github.com/anthropics/claude-code) — extraction + discovery
- [FastAPI](https://github.com/fastapi/fastapi), [SQLAlchemy](https://github.com/sqlalchemy/sqlalchemy), [Tailwind](https://tailwindcss.com)
