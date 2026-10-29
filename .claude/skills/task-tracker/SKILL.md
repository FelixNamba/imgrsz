---
name: task-tracker
description: FIFO task tracker for this project. Use when the user asks to add, list, reorder, start, finish or drop tasks, asks "what's next", or asks for a report on a done or terminated task. Maintains AI/backlog.md and writes reports to AI/reports/YYYY-MM-DD/<task>.md.
---

# Task tracker

Single source of truth: `AI/backlog.md`. Work it top-down (FIFO) unless the user names a task. Do not keep a second task list anywhere — no TODO comments, no issue mirror, no notes in other docs.

Follow `CLAUDE.md`: `AI/` is the docs source of truth, secrets only in `credentials.env`, never publish anything to Claude servers.

## Backlog format

```markdown
# Backlog

FIFO queue: work the first unchecked task. Order = priority. Closed tasks are
removed; their report is the record.

- [ ] **T1 · Short name** — 2026-10-29
  - **Goal:** one sentence: the outcome when this is done.
  - **Description:** what to do, constraints, and how to know it worked.
```

Rules:
- `T<n>` IDs are permanent. Never renumber when reordering.
- Next ID = highest `T<n>` in `AI/backlog.md` or in any `AI/reports/**/*.md` + 1 (reports record their task ID, so IDs stay unique after a task is closed).
- One task per top-level bullet. `Goal` and `Description` are required; if the user leaves either out, ask once before creating.
- Keep the header line `# Backlog` and the format block when the file starts empty; tasks go below it.

## Flows

### Add
1. Read `AI/backlog.md`.
2. Default position: append to the bottom. If the user says `top`, `after T3`, or `before T5`, insert there instead.
3. Write the task with the next ID, today's date, goal and description. Keep the user's wording for the goal.
4. Reply with the ID, position, and a one-line restatement.

### List / what's next
Show the queue in order, one line per task: `T3 · name — goal`. Mark the first as **next**. If empty, say the backlog is empty.

### Reorder
Only on request (`T3 top`, `T1 after T4`). Move the bullet and its nested fields exactly as written; never renumber.

### Work a task
When the user says "do T3", "next", "start it", or names the task:
1. Read the full task. If the description is too vague to start, ask one clarifying question, then proceed.
2. Do the work under `CLAUDE.md` (search and extend existing code/docs; no duplication).
3. Run the acceptance checks written in the description. Never report done on untested work; report failures and partial results as such.
4. Write the report, remove the task, and state the next task.

Do tasks strictly in order unless the user names a different one.

### Complete → report
1. Write `AI/reports/YYYY-MM-DD/<task-name>.md`, where the folder date is the day the task is closed and `<task-name>` is the short name in kebab-case (`hibernate-deploy-scripts.md`). Create the folder if needed.
2. Only after the report exists on disk, remove the task from `AI/backlog.md`.
3. Reply with the report path and the next task.

Report template:

```markdown
# <Short name>

- **Task:** T4
- **Status:** done
- **Date:** 2026-10-29
- **Goal:** <original goal text>

## What was done
- ...

## How to check
1. `<exact command or action>` → expected result.

## Notes
- Follow-ups, caveats, links to files/commits. "None" if empty.
```

"How to check" must be runnable and specific: exact command plus expected output, not "looks good".

### Terminate
Same path and template with `**Status:** terminated` and a `## Why it was stopped` section. Ask for the reason if the user did not give one, record any follow-ups, then remove the task from the backlog.

### Report on demand
If the user asks for a report on a task, write it from work already done. Never invent steps.

## Hard rules
- Remove a task only after its report file exists on disk.
- Never delete a report.
- Never edit a task's goal or description unless the user asks.
- If asked to clean up the backlog, show what would change and confirm before writing.
