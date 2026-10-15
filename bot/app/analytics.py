"""Public stats export (stats.json for the /case page)."""
import json
import os
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import config
from .db import DB


def _bounds(now: float | None = None) -> tuple[int, int]:
    tz = ZoneInfo(config.tz)
    dt = datetime.fromtimestamp(now or time.time(), tz)
    day = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    month = day.replace(day=1)
    return int(day.timestamp()), int(month.timestamp())


def compute_stats(db: DB, now: float | None = None) -> dict:
    day, month = _bounds(now)

    def gens(since):
        return db.one("SELECT COUNT(*) c FROM jobs WHERE status='done' AND finished_at>=?", (since,))["c"]

    def spent(since):
        return db.one("SELECT COALESCE(-SUM(amount),0) s FROM ledger WHERE reason='job' AND ts>=?", (since,))["s"]

    return {
        "unique_users": db.one("SELECT COUNT(*) c FROM users")["c"],
        "generations_today": gens(day),
        "generations_month": gens(month),
        "spent_r_today": spent(day),
        "spent_r_month": spent(month),
        "updated_at": datetime.now(ZoneInfo(config.tz)).isoformat(timespec="seconds"),
    }


def export_stats(db: DB, path: str | None = None) -> dict:
    stats = compute_stats(db)
    p = Path(path or config.stats_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(stats, ensure_ascii=False))
    os.replace(tmp, p)  # atomic: the page never reads a half-written file
    return stats
