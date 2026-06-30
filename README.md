# SaikoLook

An email triage assistant that analyzes and prioritizes your inbox using AI. Fetches Gmail messages and uses an LLM to assess urgency, whether a reply is needed, and task weight — then surfaces unhandled items in a unified dashboard.

- Runs fully offline by default (LLM calls, notifications, and Postgres are optional upgrades)
- Emails are read-only — fetched via IMAP `BODY.PEEK`, no send or write permissions
- All fetched mail is stored locally in SQLite (`data/ReplyGuard.db`, git-ignored)

---

## Quick Start

### Prerequisites

- Docker (recommended), or Python 3.10+ and Node.js 20+
- A Gmail app password — enable 2-step verification then generate a 16-character password at https://myaccount.google.com/apppasswords

### 1. Set up secrets

```bash
cp secrets/gmail.env.example secrets/gmail.env
# Edit secrets/gmail.env and fill in your Gmail address and app password:
#   GMAIL_ADDRESS=you@gmail.com
#   GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
```

If you want LLM analysis, SMTP/Slack notifications, or Postgres, also run:

```bash
cp secrets/app.env.example secrets/app.env
# Uncomment and fill in only what you need (e.g. ANTHROPIC_API_KEY)
```

> `secrets/gmail.env` and `secrets/app.env` are git-ignored. Never commit API keys or credentials.

### 2. Run with Docker

```bash
# API + frontend together
docker compose -f docker/docker-compose.yml --profile frontend up --build

# API only
docker compose -f docker/docker-compose.yml up api

# API + frontend + Postgres
docker compose -f docker/docker-compose.yml --profile full up
```

Then open:
- Dashboard: http://localhost:5173
- API health check: http://localhost:8000/health

### 3. Run without Docker

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
mkdir -p data
uvicorn app.main:app --reload --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

### 4. Stop

```bash
docker compose -f docker/docker-compose.yml down
```

---

## GitHub Integration (optional)

Pulls in PR/issue review requests, mentions, comments, and assignments. Uses a read-only OAuth App with the `notifications` scope only — no write permissions.

1. **Create an OAuth App**: GitHub → Settings → Developer settings → OAuth Apps → New OAuth App
   - Homepage URL: `http://localhost:5173`
   - Authorization callback URL: `http://127.0.0.1:8000/auth/github/callback`

2. **Add credentials** to `secrets/github.env`:

   ```bash
   cp secrets/github.env.example secrets/github.env
   # GITHUB_OAUTH_CLIENT_ID=...
   # GITHUB_OAUTH_CLIENT_SECRET=...
   ```

3. **Connect**: in the dashboard, go to account settings → GitHub → "Connect with GitHub"

---

## Configuration

All settings go in `secrets/app.env` (optional — sensible defaults are provided).

| Setting | Default | Description |
|---|---|---|
| `ANALYZER` | `stub` | LLM provider: `gemini` / `anthropic` / `openai` / `ollama`. Falls back to stub if unset. Each email is analyzed once and the result cached. |
| `GEMINI_API_KEY` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | unset | API key for LLM analysis (Gemini has a free tier) |
| `OLLAMA_BASE_URL` | unset | URL of a local Ollama instance (e.g. `http://localhost:11434`). Use with `ANALYZER=ollama` for fully local inference. |
| `LLM_MODEL` | provider default | Override the model (e.g. `gemini-2.5-flash-lite`, `qwen2.5`) |
| `NOTIFIER` | `log` | `email` or `slack` to send real notifications (requires SMTP/Webhook config) |
| `AUTH_ENABLED` | `false` | Set to `true` to enable JWT auth (requires `JWT_SECRET`) |
| `DATABASE_URL` | local SQLite | Set to a Postgres URL to switch databases |
| `SCHEDULER_ENABLED` | `true` | Enables periodic email ingestion (default every 300 seconds) |

---

## Database

- Default: **local SQLite** (`sqlite:///./data/SaikoLook.db`) — no credentials needed, schema auto-created on startup
- To use shared Postgres: set `DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/SaikoLook` in `secrets/app.env`, then start with `--profile pg` or `--profile full`
- DB files (`*.db`) are git-ignored since they contain personal email content

---

## Tests

```bash
source .venv/bin/activate
pytest -q                                  # unit tests
PYTHONPATH=. python tests/_smoke_e2e.py    # offline e2e smoke test
```
