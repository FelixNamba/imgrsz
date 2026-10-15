# imgrsz — One-Day-Offer build plan (2026-10-15)

## Context
Showcase for an AI Product Manager one-day-offer. Product: **imgrsz**, a Telegram bot that makes an image fit upload requirements (size, dimensions, format, metadata, safe zones; extending or upscaling with AI). Delivered in one day with: bot, landing page, `/case` showcase subpage with live stats, public GitHub repo with full docs, Docker deploy, and Telegram Ads creatives. Everything is self-hosted. **Nothing is published on Claude servers.**

## Decisions made
| Topic | Decision |
|---|---|
| Name / bot / domain | imgrsz · @imgrsz_bot (or the closest free name) · imgrsz.ru or .kz |
| Text LLM | GigaChat API (brief, plan JSON, vision check, moderation) |
| Image edit model | 2nd provider: **OpenRouter (Gemini image) vs fal.ai**, chosen after a reachability test from the VPS. The code sits behind a `ImageEditProvider` interface so we can switch later. |
| Hosting | serverspace.ru VPS, Ubuntu 24.04, 2 vCPU / 4 GB, Docker |
| Pricing | brief free · technical edit **5 r.** · AI edit **39 р.** (was 30, raised after measuring wide extensions) · welcome bonus **500 r.** · no payments yet |
| Analytics | own events in SQLite → `stats.json` (cron) + Yandex Metrica on the landing page + UTM passed via `/start <payload>` |
| Ads | your production Telegram Ads account; I prepare creatives, targeting and UTM links |
| Language | bot, landing and `/case` in RU · repo docs and the `AI/` folder in EN |
| Repo | public, on your GitHub account |

## Suggested image edit types (from research + common upload specs)
**Technical, 5 р. (Pillow, deterministic):** resize to px · crop to ratio (1:1, 4:5, 3:4, 16:9, 9:16) · compress to ≤ N KB/MB · convert (HEIC/PNG/WEBP → JPG and so on) · DPI or print size (e.g. 35×45 mm) · pad or letterbox with a colour · fix orientation/rotate · sRGB/grayscale · strip EXIF/GPS/XMP · flatten transparency onto white · safe-zone check with a preview overlay (avatar circle, stories 9:16).
**AI, 39 р. (image provider):** extend the canvas (outpaint) · upscale/enhance · remove or replace the background (white for marketplaces and documents) · remove objects · reframe the subject into the safe zone · restore/denoise · light and colour correction.
**Metadata (decided):** every output image is saved with **no AI metadata at all** (EXIF/XMP/IPTC/C2PA stripped; Pillow re-encodes without metadata). Every result message from the bot includes a disclaimer that the image was processed with AI.

## Bot workflow
1. User sends a photo with a free-form text (or adds the text afterwards).
2. GigaChat returns a RU brief plus a JSON plan `{ops:[...], ai:true|false, price}` → buttons ✅ Confirm / ✏️ Edit.
3. Edit → the user's text plus the previous brief go back to step 2 (loop, capped at 5).
4. Confirm → balance check → pipeline: deterministic ops (Pillow) ± AI op (provider) → validation (dimensions, size, format).
5. The bot sends the file as a document (no Telegram recompression) plus "Списано N р. · Остаток M р.". Real provider cost is logged.
Extras: `/start` with a UTM payload grants 500 р. once per user · `/balance` · `/help` · moderation before every generation.

## Architecture (goes into the docs as a Mermaid scheme)
```
Telegram ⇄ bot (Python 3.12, aiogram 3) ── GigaChat API (brief/plan/moderation)
                 │                      └─ ImageEditProvider (OpenRouter | fal.ai)
                 ├─ SQLite (users, balances, briefs, jobs, events, costs)
                 └─ exporter (cron 5 min) → /srv/www/stats.json
Caddy (TLS) → /  landing · /case showcase · /stats.json
```
docker-compose: `bot`, `caddy`, `exporter` (one image, separate command). GigaChat needs the Russian Trusted Root CA baked into the image.

## Repo layout
```
imgrsz/
  CLAUDE.md
  AI/  PLAN.md  PRD.md  ARTIFACTS.md  TECH.md  PRODUCT.md  ANALYTICS.md
       DEPLOY.md (AI-tailored runbook: first deploy, prod down, migration to a new VPS, rollback, key rotation)
       ← AI/ holds AI documentation only (no ads, no prod files)
  ads/  creatives.md  targeting.md  utm.md   ← ready-to-launch ads
  credentials.env               ← yours, already has BOT_TOKEN; gitignored, never committed
  bot/  app/{handlers,llm,providers,pipeline,billing,analytics,db}.py  tests/
  web/  index.html  case/index.html  assets/
  deploy/  Dockerfile  docker-compose.yml  Caddyfile  .env.example  backup.sh
  README.md
```
Pipeline ops are pure functions with pytest coverage. Providers sit behind one interface with a fake provider for tests.

## Landing page (`/`) — style from `/initial/`
Warm off-white background (#F3F0E8), serif headlines (Cormorant/EB Garamond), pill chips, one accent (blue #0A84FF), phone mockups of the real bot chat, a few emoji.
Scroll 1: hero image, before→after, one-line pitch, CTA "Открыть в Telegram" (deep link `?start=landing`). Scroll 2: prices (1 AI generation = 39 р., technical = 5 р., 500 р. on start). Footer: disclaimers (no storage beyond N days, AI-result labelling, legal-content-only rule, Metrica cookies, not a public offer).

## Showcase page (`/case`) — RU, labels of 1–3 words, details behind "?"
- **Top stats** from `stats.json` (fetched on load): unique users · generations today / month · р. spent today / month.
- **Hypothesis** · **Prototype** · **Real testing** · **Data collection** · **Acceptance criteria** (e.g. ≥30 activated users, ≥40% confirm→result, CAC < X, AI cost per job ≤ $0.15).
- **Towards production:** unit economics (р. price vs real cost, margin, payback) · safety (anti prompt injection: brief as structured JSON and an allow-listed ops schema; user text never reaches tools directly · law/ethics filter: GigaChat moderation + provider NSFW, no documents forgery or face swaps of third parties) · production servers (HA, backups, Postgres, S3, queue) · data rules and disclaimers (retention, 152-ФЗ / KZ law, consent) · marketing automation (trigger messages, referral) · analytics integration (events → ClickHouse/Metrica/DataLens).
- **AI harness:** business goals → metrics tree via a unit-economics growth model · unified strategic agent: reads metrics and user requests, clusters JTBD (Ivan Zamesin's method: job, context, criteria, alternatives) → proposes new segments and experiments.
- **Architecture:** a dedicated showcase-quality architecture image (`web/assets/architecture.png/svg`, made later in the day) + short notes.

## Ads (`ads/` at repo root)
3–5 Telegram Ads texts (≤160 chars, RU) per pain (form won't accept the photo / need it wider / need it under 1 MB), a list of target IT/design/HR channels, UTM deep links `t.me/imgrsz_bot?start=tgads_<creative>`, and an erid/labelling checklist for your account.

## Your steps (⏸ = I wait for you)
1. ⏸ Register the domain (serverspace or another registrar) → point A records `@` and `www` to the VPS IP.
2. ⏸ Create the serverspace VPS (Ubuntu 24.04, 2 vCPU/4 GB) → give me SSH access (key) or run my commands.
3. ⏸ Run the reachability test on the VPS (I provide a script): api.telegram.org, ngw.devices.sberbank.ru, gigachat.devices.sberbank.ru, openrouter.ai, fal.run. **Pick the image provider from the result.**
4. ⏸ GigaChat: register at developers.sber.ru (Sber ID), get an Authorization key with scope `GIGACHAT_API_PERS` or `_CORP`, and check the balance/freemium tokens.
5. ⏸ Image provider account + API key + top-up of about $10.
6. ✅ Bot created, token in `credentials.env`. Remaining: set avatar/description (I provide the texts).
7. ⏸ GitHub: create the public repo `imgrsz` or run `! gh auth login` so I can push.
8. ⏸ Yandex Metrica: create a counter for the domain and send the ID.
9. ⏸ Test the bot yourself, then invite 5–10 friends for the first real data.
10. ⏸ Launch the Telegram Ads campaign from `ads/` in your account (labelling).
11. ⏸ Final review of `/case` and send the link to the reviewer.

## Timeline (today)
| Slot | Work |
|---|---|
| 0:00–0:30 | Repo scaffold, CLAUDE.md, AI/ docs (PLAN, PRD, ARTIFACTS) · you do steps 1–2, 4–7 in parallel |
| 0:30–3:30 | Bot: handlers, GigaChat brief loop, pipeline, billing, events, tests |
| 3:30–4:30 | Image provider integration after the step 3 test, end-to-end on a local Docker |
| 4:30–5:30 | Deploy to the VPS, Caddy TLS, exporter → stats.json |
| 5:30–7:00 | Landing page + images (generated via the image provider and real bot screenshots) + /case |
| 7:00–8:00 | TECH/DEPLOY/ANALYTICS docs, `ads/`, architecture image, README, final push · you launch ads |

## Artefact list (→ `AI/ARTIFACTS.md`)
GitHub repo · Telegram bot · landing page `/` · showcase `/case` · `stats.json` · Docker image + compose · DEPLOY runbook · PRD · tech and product docs · analytics spec + Metrica · ad creatives + UTM map · architecture scheme · landing visuals.

## CLAUDE.md (draft, final ≈10 lines)
```
# imgrsz
TG bot fitting images to upload requirements. RU UI, EN docs.
Source of truth: AI/ (PLAN, PRD, TECH, DEPLOY). Read before changes.
Stack: Python 3.12, aiogram 3, SQLite, Pillow, GigaChat, ImageEditProvider. Docker + Caddy.
Run: docker compose -f deploy/docker-compose.yml up -d · Test: pytest bot/tests
Rules:
- No duplication: one fact lives in one file; elsewhere link to it. Search before adding code/docs; extend existing ones.
- Secrets only in credentials.env (gitignored). Prices/bonus only in config.
- AI/ = AI docs only; ads in ads/; production code in bot/, web/, deploy/.
- Nothing is published to Claude servers.
```

## Verification
- `pytest` for pipeline ops (size, ratio, KB limit, EXIF stripped), the billing ledger, and brief JSON schema validation.
- Local `docker compose up` with the fake provider → full bot dialog in Telegram.
- On the VPS: real flow, both 5 р. and 39 р. paths; balance and events in SQLite; `curl https://<domain>/stats.json`; `/case` shows the numbers; Lighthouse mobile check of `/` and `/case`; the landing deep link with UTM shows up in the events.
- Runbook dry-run: `docker compose down` → restore following DEPLOY.md "prod down".

Sources: [GigaChat models](https://developers.sber.ru/docs/ru/gigachat/models/updates) · [GigaChat image generation](https://developers.sber.ru/docs/ru/gigachat/guides/images-generation) · [Passport photo specs](https://passlens.com/blog/passport-photo-file-size-checker-guide) · [Telegram Ads 2026](https://ppc.world/articles/reklama-v-telegram-v-2026-godu-benchmarki-i-stoit-li-zapuskat-kampanii-seychas/amp/)
