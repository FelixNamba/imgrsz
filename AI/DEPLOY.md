# DEPLOY — runbook for AI agents and humans

Facts:
- Prod host: `root@185.200.86.246` (serverspace, Ubuntu 24.04, 1 vCPU / 1 GB plus 2 GB swap).
- SSH key: `env/imgrsz.pem` (local, gitignored).
- App dir: `/opt/imgrsz` (git clone of `github.com/FelixNamba/imgrsz`).
- Secrets: `/opt/imgrsz/credentials.env`, chmod 600, never in git.
- Data: `/opt/imgrsz/data/imgrsz.sqlite`. Backups: `/root/backups/` (daily, same host); off-server copies: `deploy/pull_backup.sh <ip>` → local `backups/` (gitignored).
- Compose: `docker compose -f deploy/docker-compose.yml` (services `bot` and `caddy`), run from `/opt/imgrsz`.

Rules for agents: before any destructive step (rm, `down -v`, DB restore), back up the DB first. Never print secrets. Long commands run under `nohup … &` because the provider drops idle SSH sessions.

## Shortcuts
```bash
SSH="ssh -i env/imgrsz.pem -o ServerAliveInterval=15 root@185.200.86.246"
DC="docker compose -f deploy/docker-compose.yml"
```

## 1. First deploy (new server)
Fresh Ubuntu LTS VPS (≥1 GB RAM) with root SSH by key. From the repo root on the laptop:
```bash
deploy/bootstrap.sh <ip> [backups/imgrsz-<date>.sqlite]     # SSH_KEY=<path> if not env/imgrsz.pem
```
It sets up swap, Docker and the firewall, clones the repo, uploads `credentials.env` (and the DB if given), adds the backup cron, builds and starts the stack, then runs `scripts/check_access.sh`. Safe to re-run. Then point DNS at the new IP (section 7) and run the health check (section 5).

## 2. Regular release
```bash
git push
$SSH 'cd /opt/imgrsz && git pull -q && nohup docker compose -f deploy/docker-compose.yml up -d --build > /root/deploy.log 2>&1 &'
```
Web-only changes (`web/`) go live on `git pull`; the directory is bind-mounted, so no rebuild is needed.

## 3. Production down
Work top to bottom and stop when it is fixed.
1. **Which part?** `curl -s -o /dev/null -w "%{http_code}" https://imgrsz.ru/` → web; send `/start` to the bot → bot.
2. **Host alive?** `$SSH uptime`. No answer → reboot from the serverspace panel and go to step 3.
3. **Containers:** `$SSH "cd /opt/imgrsz && $DC ps"`. Anything not `running` → `$DC up -d`.
4. **Logs:** `$SSH "cd /opt/imgrsz && $DC logs --tail 100 bot"`.
   - `TelegramConflictError` → another instance is polling with the same token (often a local dev run). Stop it.
   - `401` on GigaChat oauth → the auth key was revoked or expired. Get a new one at developers.sber.ru, then update `credentials.env` and run `$DC up -d`.
   - `SSL: CERTIFICATE_VERIFY_FAILED` on GigaChat → refresh `deploy/certs/` from gu-st.ru.
   - `openrouter 402` → the balance is empty: top up. `openrouter 429/5xx` → temporary; to keep the bot answering, set `IMAGE_PROVIDER=fake`, which disables real AI edits.
   - `database is locked` / disk full → `df -h`; clean with `docker system prune -f`.
   - OOM (`dmesg | tail`) → check `free -h` and swap; `mem_limit` is in compose.
5. **Reachability:** `$SSH 'bash -s' < scripts/check_access.sh`. `000` means blocked. Escalate to the provider or switch the image provider.
6. **Rollback:** `$SSH "cd /opt/imgrsz && git log --oneline -5 && git checkout <good_sha> && $DC up -d --build"`.
7. **Restore DB** (only if corrupted): `$DC stop bot && cp /root/backups/imgrsz-<date>.sqlite data/imgrsz.sqlite && $DC start bot`.

## 4. Migration to a new server
1. Create the new VPS and add the SSH key.
2. Old host: `$SSH "cd /opt/imgrsz && $DC stop bot"`, then `deploy/pull_backup.sh <old_ip>` (final snapshot, nothing changes after the stop).
3. `deploy/bootstrap.sh <new_ip> backups/imgrsz-<date>.sqlite`. Check section 5.
4. Point the domain's DNS A record at the new IP (TTL 300). Caddy issues the certificate automatically once DNS resolves.
5. Old host: `$DC down`. Keep it for 48 h, then delete it. Update the IP in this file and in `deploy/Caddyfile` (section 7).

## 5. Health check
```bash
$SSH "cd /opt/imgrsz && $DC ps && $DC logs --tail 5 bot"
curl -s http://<host>/stats.json          # updated_at no older than 5 min
```
Then in Telegram: `/start` → send a photo with "квадрат 500x500" → a 5 р. result arrives.

## 6. Key rotation
Edit `credentials.env` locally → `scp` it to the server → `$DC up -d` (recreates the containers with the new env). Never commit it.

## 7. Domain switch-on
Live: `DOMAIN="imgrsz.ru, www.imgrsz.ru"` (quoted, so `. credentials.env` works in a shell) (A records `@`, `www` → server IP). Change: edit `credentials.env` → copy it to the server → `$DC up -d --force-recreate caddy`; HTTPS is issued automatically. `deploy/Caddyfile` redirects old `http://<IP>` links to the domain; when moving to a new VPS, update that IP. Back to IP-only (domain broken): `DOMAIN=:80` and delete the redirect block.

## 8. Site versions, preview and rollback
Saved versions are annotated git tags (`git tag -l 'site-*' -n1`). `site-v3` = landing before the redesign merge (server copy: `/root/backups/web-site-v3.tar.gz`); `site-v4` = merged redesign, live since 2026-10-16. Landing styles: `web/assets/landing.css`; `/case/` still uses `web/assets/style.css`.

**Preview (not yet accepted):** new designs go to `web/preview/` → `https://imgrsz.ru/preview/`; each review round is a sibling folder (`web/preview-2/` …), earlier rounds stay for comparison (`noindex`, own `style.css`, shares `/assets/img/`). The live `/` is untouched; it goes live on `git pull` like any web change.

**Promote preview to `/`** (after acceptance):
1. `git tag -a site-vN -m "<what is live now>" && git push origin site-vN` — save the current live version first.
2. Copy the preview `index.html` → `web/index.html`, its CSS → `web/assets/landing.css`, images → `web/assets/img/`; fix paths (`/preview-N/` → `/`), drop `noindex`, restore `og:` tags, `start=` payloads → `landing_*`; delete the preview folders.
3. Release (section 2), check `https://imgrsz.ru/` and `/case/` on desktop and phone.

**Rollback the site** (any web version, ~1 min, bot untouched):
```bash
git checkout site-v3 -- web/ && git commit -m "Rollback site to site-v3" && git push
$SSH 'cd /opt/imgrsz && git pull -q'
```
Server-only emergency (GitHub unavailable): `$SSH 'cd /opt/imgrsz && git checkout site-v3 -- web/'`, or untar `/root/backups/web-site-v3.tar.gz` into `/opt/imgrsz/`. Then commit the same rollback locally so the next pull does not undo it.

## 9. Hibernate and wake up
Pausing the project for a long time: nothing is lost if git, `credentials.env`, `env/` (SSH keys) and the final DB snapshot survive.

**Hibernate**
1. `git status` is clean and pushed (`git log origin/main..main` is empty).
2. `$SSH "cd /opt/imgrsz && $DC stop bot"`, then `deploy/pull_backup.sh <ip>`: the final DB in `backups/`.
3. Copy `credentials.env`, `env/` and `backups/` to durable storage beyond this laptop (password manager or encrypted cloud drive).
4. `$SSH "cd /opt/imgrsz && $DC down"`, then delete the VPS in the serverspace panel (or keep paying to keep it). Mark the Prod host line above as hibernated.
5. Keep the domain `imgrsz.ru` renewed, or it is lost. Telegram bot tokens do not expire; the bot just stays silent.

**Wake up**
1. Restore `credentials.env`, `env/`, `backups/` into the repo root.
2. Check the outside world, since keys and models age: GigaChat auth key, OpenRouter balance, `deploy/certs/` (section 3, step 4), and that `OPENROUTER_MODEL` / `GIGACHAT_MODEL` still exist.
3. Refresh dependencies locally: bump `bot/requirements.txt`, `python:3.12-slim` in `deploy/Dockerfile`, `caddy:` in `deploy/docker-compose.yml`; run `pytest bot/tests` and a local bot with a test token (TECH → Local dev).
4. New VPS → `deploy/bootstrap.sh <new_ip> backups/<final>.sqlite` (section 1), DNS (section 7), health check (section 5). Update the IP in this file and in `deploy/Caddyfile`.
