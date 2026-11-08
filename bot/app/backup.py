"""Daily SQLite backup inside the bot process."""
import asyncio
import logging
import sqlite3
import time
from pathlib import Path

from .config import config

log = logging.getLogger("imgrsz.backup")
BACKUP_DIR = Path("/backups")
RETENTION_DAYS = 14


def backup_once() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    dest = BACKUP_DIR / f"imgrsz-{time.strftime('%Y-%m-%d')}.sqlite"
    src = sqlite3.connect(config.db_path)
    dst = sqlite3.connect(dest)
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()
    cutoff = time.time() - RETENTION_DAYS * 86400
    for f in BACKUP_DIR.glob("imgrsz-*.sqlite"):
        if f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)
    return dest


async def backup_loop(every: int = 86400) -> None:
    while True:
        try:
            dest = await asyncio.to_thread(backup_once)
            log.info("backup written: %s", dest)
        except Exception:
            log.exception("backup failed")
        await asyncio.sleep(every)
