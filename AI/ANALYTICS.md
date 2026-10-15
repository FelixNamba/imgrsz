# ANALYTICS — imgrsz

## Events (`events` table: tg_id, name, props JSON, ts)
| Event | When | Props |
|---|---|---|
| `start` | /start | `source` (deep-link payload, e.g. `tgads_c1`, `landing_hero`), `new` |
| `image_received` | image accepted | job_id, width, height, format, size_kb |
| `brief_shown` | brief with buttons | job_id, iteration, ai, price |
| `clarify` | LLM asked a question | job_id |
| `brief_edit` | ✏️ pressed | job_id |
| `brief_failed` | LLM error | job_id, error |
| `refused` | ethics refusal | job_id, reason |
| `insufficient_balance` | not enough r. | job_id, price, balance |
| `confirmed` | ✅ pressed | job_id, ai, price |
| `delivered` | result sent | job_id, ai, price, seconds, width, height, kb, fmt |
| `failed` | processing error (no charge) | job_id, error |

Costs per job: `jobs.llm_tokens`, `jobs.provider_cost_usd` (real figure from OpenRouter `usage.cost`). Money flow: the `ledger` table (+bonus / −charge).

## Public stats (`/stats.json`, every 5 min, TZ Asia/Almaty)
`unique_users`, `generations_today`, `generations_month`, `spent_r_today`, `spent_r_month`, `updated_at`. "Generations" = jobs with `status=done`.

## Queries
```sql
-- Funnel by source
SELECT u.source,
  COUNT(DISTINCT u.tg_id) starts,
  COUNT(DISTINCT CASE WHEN e.name='image_received' THEN e.tg_id END) activated,
  COUNT(DISTINCT CASE WHEN e.name='brief_shown' THEN e.tg_id END) briefed,
  COUNT(DISTINCT CASE WHEN e.name='confirmed' THEN e.tg_id END) confirmed,
  COUNT(DISTINCT CASE WHEN e.name='delivered' THEN e.tg_id END) delivered
FROM users u LEFT JOIN events e ON e.tg_id=u.tg_id GROUP BY u.source;

-- Unit cost per job type (RUB at USD_RUB=82, GigaChat 1.5 ₽/1k tokens)
SELECT CASE WHEN price=30 THEN 'ai' ELSE 'tech' END kind, COUNT(*) jobs,
  ROUND(AVG(provider_cost_usd*82 + llm_tokens/1000.0*1.5),2) cost_rub, AVG(price) price_r
FROM jobs WHERE status='done' GROUP BY kind;

-- Brief iterations distribution
SELECT iterations, COUNT(*) FROM jobs WHERE status IN ('done','draft') GROUP BY 1;

-- Repeat usage (2nd job within 7 days)
SELECT COUNT(*) FROM (SELECT tg_id, MIN(finished_at) f FROM jobs WHERE status='done' GROUP BY tg_id) a
WHERE EXISTS (SELECT 1 FROM jobs j WHERE j.tg_id=a.tg_id AND j.status='done' AND j.finished_at>a.f AND j.finished_at<a.f+7*86400);
```
Run on prod: `ssh … 'sqlite3 -header -column /opt/imgrsz/data/imgrsz.sqlite "<query>"'`.

## Acceptance criteria
See `AI/PRD.md` → Acceptance criteria.

## Not yet
Yandex Metrica (the service was down on 2026-10-15). Landing attribution currently comes only from deep-link payloads (`landing_hero`, `landing_prices`, `landing_nav`, `case*`).
