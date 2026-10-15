#!/usr/bin/env bash
# Daily SQLite backup (cron on the VPS): keeps 14 days in /root/backups.
set -euo pipefail
mkdir -p /root/backups
sqlite3 /opt/imgrsz/data/imgrsz.sqlite ".backup /root/backups/imgrsz-$(date +%F).sqlite"
find /root/backups -name 'imgrsz-*.sqlite' -mtime +14 -delete
