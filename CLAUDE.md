# imgrsz
Telegram bot that makes an image fit upload requirements. RU UI, EN docs.
Source of truth: `AI/` (PLAN, PRD, ARTIFACTS, TECH, DEPLOY). Read it before making changes.
Stack: Python 3.12, aiogram 3, SQLite, Pillow, GigaChat, ImageEditProvider. Docker + Caddy.
Run: `docker compose -f deploy/docker-compose.yml up -d` · Test: `pytest bot/tests`

Rules:
- No duplication: each fact lives in exactly one file; everywhere else links to it. Search before adding code or docs, and extend what exists.
- Secrets live only in `credentials.env` (gitignored). Prices and bonus live only in config.
- `AI/` holds AI docs only; ads go in `ads/`; production code goes in `bot/`, `web/`, `deploy/`.
- Never publish anything to Claude servers.
