# imgrsz

Telegram bot [@imgrsz_bot](https://t.me/imgrsz_bot) that makes any image fit upload requirements: size, aspect ratio, file weight, format, DPI, metadata. It also extends, enhances and changes backgrounds with AI.

Send an image and describe the need in your own words → confirm the AI brief → get the file.

- Landing: http://185.200.86.246/ · Case: http://185.200.86.246/case/
- Stack: Python 3.12, aiogram 3, Pillow, GigaChat (brief), OpenRouter / Gemini (image edits), SQLite, Docker, Caddy

## Docs (`AI/`)
| | |
|---|---|
| [PLAN](AI/PLAN.md) | one-day plan |
| [PRD](AI/PRD.md) | problem, hypothesis, scope, acceptance criteria |
| [PRODUCT](AI/PRODUCT.md) | user flow, pricing, bot profile |
| [TECH](AI/TECH.md) | architecture, modules, decisions |
| [DEPLOY](AI/DEPLOY.md) | runbook: deploy, prod down, migration |
| [ANALYTICS](AI/ANALYTICS.md) | events, stats.json, SQL |
| [ARTIFACTS](AI/ARTIFACTS.md) | list of project artefacts |

Ads: [`ads/`](ads/). Quick start: [TECH → Local dev](AI/TECH.md#local-dev), [DEPLOY](AI/DEPLOY.md).
