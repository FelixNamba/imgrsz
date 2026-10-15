# PRD — imgrsz

## Problem
People upload images to forms and sites that have strict requirements: file size, dimensions, format, colour mode, safe zones, and no AI metadata. When someone is in a hurry, a rejected upload blocks the task. It is worse when the image has to be **wider** or **higher quality** than the original.

## Hypothesis
IT and office Telegram users with an urgent upload task will hand the fix to a bot: send a photo and describe the need in their own words. They will confirm the AI brief and get a compliant file in under 1 minute.

## Target users / JTBD
- "When a form rejects my photo, I want to make it fit in a minute, so that I can finish the application."
- "When I need a banner or cover at a bigger aspect ratio, I want to extend the image naturally, so that I don't have to reshoot or open Photoshop."
- "When I have to send a photo without metadata, I want it cleaned, so that it passes checks and leaks nothing."

## Scope v0 (today)
| # | Requirement |
|---|---|
| F1 | User sends an image (photo or document) plus free-form text, in RU |
| F2 | GigaChat produces a short RU brief and a JSON plan; buttons ✅ Confirm / ✏️ Edit |
| F3 | Edit → re-brief with the user's correction (max 5 iterations) |
| F4 | Confirm → the deterministic pipeline (Pillow) runs, plus an AI edit (image provider) when needed |
| F5 | The result is sent as a document with the charge, the balance and an AI-processing disclaimer |
| F6 | New user gets a 500 р. welcome bonus (once) |
| F7 | Pricing: brief free · technical edit · AI edit (values in `bot/app/config.py`) |
| F8 | All output is stripped of metadata (EXIF/XMP/IPTC/C2PA) |
| F9 | Events and real provider cost are logged; `stats.json` is exported every 5 min |
| F11 | Admin bot: copies of all results; `/drop @username` resets a user for testing |
| F10 | Moderation before generation: legal content only, no document forgery |

Out of scope: payments, web UI, batch processing.

## Supported operations
Technical: resize · crop to ratio · compress to ≤N KB · convert format · DPI / print size · pad · rotate · colour mode · strip metadata · flatten transparency · safe-zone preview.
AI: extend to any ratio (whole source kept) · upscale/enhance · background removal. No new scenes, no face changes: a resize service, not a photo editor.

## Metrics
North star: **delivered results per week**.
Funnel: start → image sent → brief shown → confirmed → delivered → 2nd job.
Cost: provider cost per job (RUB) vs р. charged; brief iterations per job.

## Acceptance criteria (prototype → invest further)
- ≥30 activated users (sent ≥1 image) from ads in the first week
- confirm → delivered ≥80%; brief shown → confirmed ≥40%
- ≥25% of activated users make a 2nd job within 7 days
- average real AI cost per AI job ≤ $0.15 (≈ 1/3 of the AI price)
- 0 moderation incidents

## Risks
GigaChat access from KZ (Sber ID) · reachability of the image provider from the VPS · AI output quality on extension · abuse (forgery) → moderation plus disclaimers.
