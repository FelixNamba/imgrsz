#!/usr/bin/env bash
# Manual SQLite backup fallback. Scheduled backups run inside the bot process.
set -euo pipefail
mkdir -p /root/backups
sqlite3 /srv/sites/imgrsz/data/imgrsz.sqlite ".backup /root/backups/imgrsz-$(date +%F).sqlite"
find /root/backups -name 'imgrsz-*.sqlite' -mtime +14 -delete
