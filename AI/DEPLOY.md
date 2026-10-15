# DEPLOY — runbook for AI agents and humans

Facts:
- Prod host: `root@185.200.86.246` (serverspace, Ubuntu 24.04, 1 vCPU / 1 GB plus 2 GB swap).
- SSH key: `env/imgrsz.pem` (local, gitignored).
- App dir: `/opt/imgrsz` (git clone of `github.com/FelixNamba/imgrsz`).
- Secrets: `/opt/imgrsz/credentials.env`, chmod 600, never in git.
- Data: `/opt/imgrsz/data/imgrsz.sqlite`. Backups: `/root/backups/`.
- Compose: `docker compose -f deploy/docker-compose.yml` (services `bot` and `caddy`), run from `/opt/imgrsz`.

Rules for agents: before any destructive step (rm, `down -v`, DB restore), back up the DB first. Never print secrets. Long commands run under `nohup … &` because the provider drops idle SSH sessions.

## Shortcuts
```bash
SSH="ssh -i env/imgrsz.pem -o ServerAliveInterval=15 root@185.200.86.246"
DC="docker compose -f deploy/docker-compose.yml"
```

## 1. First deploy (new server)
```bash
$SSH 'fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile && echo "/swapfile none swap sw 0 0" >> /etc/fstab'
$SSH 'curl -fsSL https://get.docker.com | sh && apt-get install -y sqlite3 git ufw && ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 443/tcp && ufw --force enable'
$SSH 'git clone https://github.com/FelixNamba/imgrsz.git /opt/imgrsz && mkdir -p /opt/imgrsz/data'
scp -i env/imgrsz.pem credentials.env root@185.200.86.246:/opt/imgrsz/credentials.env
$SSH 'cd /opt/imgrsz && chmod 600 credentials.env && nohup docker compose -f deploy/docker-compose.yml up -d --build > /root/deploy.log 2>&1 &'
$SSH 'echo "0 3 * * * root /opt/imgrsz/deploy/backup.sh" > /etc/cron.d/imgrsz-backup'
```
Check: `bash scripts/check_access.sh` on the server (all APIs reachable), then section 5.

## 2. Regular release
```bash
git push
$SSH 'cd /opt/imgrsz && git pull -q && nohup docker compose -f deploy/docker-compose.yml up -d --build > /root/deploy.log 2>&1 &'
```
Web-only changes (`web/`) go live on `git pull`; the directory is bind-mounted, so no rebuild is needed.

## 3. Production down
Work top to bottom and stop when it is fixed.
1. **Which part?** `curl -s -o /dev/null -w "%{http_code}" http://185.200.86.246/` → web; send `/start` to the bot → bot.
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
1. Create the new VPS and add the SSH key. Run section 1 on the new host up to the point of copying the secrets (do not start the stack).
2. On the old host: `$DC stop bot && sqlite3 data/imgrsz.sqlite ".backup /root/final.sqlite"`.
3. Copy: `scp` old:/root/final.sqlite → local → new:/opt/imgrsz/data/imgrsz.sqlite, plus `credentials.env`.
4. Start on the new host: `$DC up -d --build`. Check section 5.
5. Point the domain's DNS A record at the new IP (TTL 300). Caddy issues the certificate automatically once DNS resolves.
6. Old host: `$DC down`. Keep it for 48 h, then delete it. Update the IP in this file.

## 5. Health check
```bash
$SSH "cd /opt/imgrsz && $DC ps && $DC logs --tail 5 bot"
curl -s http://<host>/stats.json          # updated_at no older than 5 min
```
Then in Telegram: `/start` → send a photo with "квадрат 500x500" → a 5 р. result arrives.

## 6. Key rotation
Edit `credentials.env` locally → `scp` it to the server → `$DC up -d` (recreates the containers with the new env). Never commit it.

## 7. Domain switch-on
Set `DOMAIN=imgrsz.ru` in `credentials.env` (and `www`, if needed: `DOMAIN=imgrsz.ru, www.imgrsz.ru`) → copy it to the server → `$DC up -d caddy`. HTTPS is issued automatically.
