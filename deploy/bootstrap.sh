#!/usr/bin/env bash
# Deploy imgrsz onto a fresh (or existing) Ubuntu VPS from the laptop. Safe to re-run.
# Usage (repo root): deploy/bootstrap.sh <host_ip> [db.sqlite]
#   db.sqlite: restore this DB (e.g. from deploy/pull_backup.sh); omitted = keep the server DB or start empty.
# Needs: credentials.env in the repo root, root SSH with $SSH_KEY (default env/imgrsz.pem).
set -euo pipefail
host=${1:?usage: deploy/bootstrap.sh <host_ip> [db.sqlite]}
db=${2:-}
key=${SSH_KEY:-env/imgrsz.pem}
dir=/opt/imgrsz
[ -f credentials.env ] || { echo "credentials.env not found (run from the repo root)"; exit 1; }
[ -z "$db" ] || [ -f "$db" ] || { echo "$db not found"; exit 1; }
opts=(-i "$key" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=15)
ssh=(ssh "${opts[@]}" "root@$host")

echo "== 1/4 system: swap, docker, firewall"
"${ssh[@]}" bash -s <<'EOF'
set -e
if ! swapon --show | grep -q /swapfile; then
  [ -f /swapfile ] || { fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile; }
  swapon /swapfile
  grep -q /swapfile /etc/fstab || echo "/swapfile none swap sw 0 0" >> /etc/fstab
fi
command -v docker >/dev/null || curl -fsSL https://get.docker.com | sh
export DEBIAN_FRONTEND=noninteractive
apt-get update -q >/dev/null && apt-get install -y -q sqlite3 git ufw >/dev/null
ufw allow OpenSSH >/dev/null && ufw allow 80/tcp >/dev/null && ufw allow 443/tcp >/dev/null && ufw --force enable >/dev/null
EOF

echo "== 2/4 code"
"${ssh[@]}" bash -s "$dir" <<'EOF'
set -e
if [ -d "$1/.git" ]; then git -C "$1" pull -q; else git clone -q https://github.com/FelixNamba/imgrsz.git "$1"; fi
mkdir -p "$1/data"
echo "0 3 * * * root $1/deploy/backup.sh" > /etc/cron.d/imgrsz-backup
EOF

echo "== 3/4 secrets${db:+ and DB}"
scp "${opts[@]}" -q credentials.env "root@$host:$dir/credentials.env"
"${ssh[@]}" "chmod 600 $dir/credentials.env"
if [ -n "$db" ]; then
  # Back up whatever DB the server already has before replacing it.
  "${ssh[@]}" bash -s "$dir" <<'EOF'
set -e
cd "$1"
docker compose -f deploy/docker-compose.yml stop bot >/dev/null 2>&1 || true
if [ -f data/imgrsz.sqlite ]; then
  mkdir -p /root/backups
  sqlite3 data/imgrsz.sqlite ".backup /root/backups/before-restore-$(date +%F-%H%M).sqlite"
fi
rm -f data/imgrsz.sqlite-wal data/imgrsz.sqlite-shm
EOF
  scp "${opts[@]}" -q "$db" "root@$host:$dir/data/imgrsz.sqlite"
fi

echo "== 4/4 build and start (log: /root/deploy.log)"
# nohup: the provider drops idle SSH sessions during long builds.
"${ssh[@]}" "cd $dir && nohup docker compose -f deploy/docker-compose.yml up -d --build > /root/deploy.log 2>&1 < /dev/null &"
sleep 5
while "${ssh[@]}" "pgrep -f 'docker compose -f deploy/docker-compose.yml up' >/dev/null"; do sleep 10; done
"${ssh[@]}" "tail -3 /root/deploy.log; cd $dir && docker compose -f deploy/docker-compose.yml ps --format '{{.Service}}: {{.Status}}'"

echo "== external APIs"
"${ssh[@]}" bash -s < scripts/check_access.sh
echo "Done. Next: point DNS A records at $host, then the health check (AI/DEPLOY.md §5)."
