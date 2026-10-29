# Backlog

FIFO queue: work the first unchecked task. Order = priority. Closed tasks are
removed; their report is the record (see `.claude/skills/task-tracker/SKILL.md`).

<!-- Format:
- [ ] **T1 · Short name** — 2026-10-29
  - **Goal:** one sentence: the outcome when this is done.
  - **Description:** what to do, constraints, and how to know it worked.
-->

- [ ] **T1 · Yandex Metrica** — 2026-10-29
  - **Goal:** Landing and case traffic is measured in Yandex Metrica, closing the top-of-funnel gap left by deep-link-only attribution.
  - **Description:** Purpose (from `AI/PLAN.md` and `AI/ANALYTICS.md` → "Not yet"): the landing currently has no pageview stats — attribution starts only when a user opens the bot via a `landing_*` / `case*` deep link, so visits that never click are invisible. Steps: (1) create a counter for `imgrsz.ru` (user action; the service was down on 2026-10-15 — retry) and provide the counter ID; (2) add the Metrica snippet with that ID to `web/index.html` and `web/case/index.html`; (3) configure one goal for clicks on Telegram CTA links (`t.me/imgrsz_bot?...`); (4) deploy per `AI/DEPLOY.md` §2. Done when both URLs return 200, a real visit and a CTA click appear in Metrica, `AI/ARTIFACTS.md` #18 is ✅, and the "Not yet" note is removed from `AI/ANALYTICS.md`.

- [ ] **T2 · Result feedback 👍/👎** — 2026-10-29
  - **Goal:** After each delivered image the user can rate the result 👍 or 👎, and a 👎 reaches the admins with the source image, the result and the prompt.
  - **Description:** Attach an inline keyboard to the result message in `bot/app/handlers.py` (~line 227, `answer_document`): 👍 → `fb:good:<job_id>`, 👎 → `fb:bad:<job_id>`. 👍 records only. 👎 re-downloads the source via `jobs.file_id` and the result via the message's document `file_id`, then notifies admins with both images plus the prompt (`plan.ai_prompt` when present, else the user request) — extend `admin.notify` in `bot/app/admin.py`, which already sends before/after with request and brief; a failed notify must never surface to the user. Log one `feedback` event per vote (`job_id`, `vote`, `ai`, `price`) and add it to the events table in `AI/ANALYTICS.md`. No re-charge, no change to the delivery flow. Done when both buttons respond, a 👎 delivers both images + prompt to `@imgrsz_admin_bot`, the event rows exist, and `pytest bot/tests` passes.

- [ ] **T3 · Case acceptance criteria rewrite** — 2026-10-29
  - **Goal:** `/case/` shows the new acceptance criteria, without the cost/margin and moderation lines.
  - **Description:** In `web/case/index.html`, the "Критерии принятия" `<ul>` (lines 59–66): replace the first `<li>` with `≥ 30% пользователей прислали изображение за неделю с момента старта бота;`; replace the third with `≥ 25% пользователей делают 2-ю задачу за 7 дней с момента активации;`; delete the `<li>`s `себестоимость ИИ-задачи ≤ 13 ₽ ($0.15) при цене 39 р. — маржа ≥ 65%;` and `0 инцидентов модерации.`; add `Сервис выдерживает unit-экономику` as an `<li>`. Keep the second `<li>` and the closing paragraph. Mirror the same bullets in `AI/PRD.md` → Acceptance criteria so page and docs do not diverge (CLAUDE.md no-duplication). Deploy per `AI/DEPLOY.md` §2. Done when `curl -s https://imgrsz.ru/case/` contains the three new lines and none of the removed text, and `AI/PRD.md` matches.
