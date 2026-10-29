#!/usr/bin/env bash
# Copy a fresh DB snapshot from the VPS to <repo>/backups/ (gitignored): the off-server copy.
# Usage (repo root): deploy/pull_backup.sh <host_ip>
set -euo pipefail
host=${1:?usage: deploy/pull_backup.sh <host_ip>}
key=${SSH_KEY:-env/imgrsz.pem}
name=imgrsz-$(date +%F-%H%M).sqlite
ssh=(ssh -i "$key" -o ServerAliveInterval=15 "root@$host")
"${ssh[@]}" "sqlite3 /opt/imgrsz/data/imgrsz.sqlite '.backup /tmp/$name'"
mkdir -p backups
scp -i "$key" -q "root@$host:/tmp/$name" "backups/$name"
"${ssh[@]}" "rm -f /tmp/$name"
echo "backups/$name ($(du -h "backups/$name" | cut -f1), integrity: $(sqlite3 "backups/$name" 'PRAGMA integrity_check'))"
