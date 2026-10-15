import os
from dataclasses import dataclass
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class Config:
    bot_token: str = _env("BOT_TOKEN")
    admin_bot_token: str = _env("ADMIN_BOT_TOKEN")
    # Telegram usernames (without @, comma-separated) allowed to receive every result via the admin bot
    admin_usernames: tuple = tuple(u.strip().lstrip("@").lower() for u in _env("ADMIN_USERNAMES", "felixnamba").split(",") if u.strip())
    gigachat_auth_key: str = _env("GIGACHAT_AUTH_KEY")
    gigachat_scope: str = _env("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")
    gigachat_model: str = _env("GIGACHAT_MODEL", "GigaChat-2-Pro")
    gigachat_base_url: str = _env("GIGACHAT_BASE_URL", "https://api.giga.chat/v1")
    gigachat_oauth_url: str = _env("GIGACHAT_OAUTH_URL", "https://ngw.devices.sberbank.ru:9443/api/v2/oauth")
    gigachat_ca_dir: str = _env("GIGACHAT_CA_DIR", str(Path(__file__).resolve().parents[2] / "deploy" / "certs"))
    image_provider: str = _env("IMAGE_PROVIDER", "fake")
    openrouter_api_key: str = _env("OPENROUTER_API_KEY")
    openrouter_model: str = _env("OPENROUTER_MODEL", "google/gemini-3.1-flash-lite-image")
    db_path: str = _env("DB_PATH", "data/imgrsz.sqlite")
    stats_path: str = _env("STATS_PATH", "web/stats.json")
    tz: str = _env("TZ_NAME", "Asia/Almaty")

    # Pricing (single source of truth, in "р.")
    welcome_bonus: int = 500
    price_technical: int = 5
    price_ai: int = 39
    max_brief_iterations: int = 5
    # Real-money estimates for cost analytics
    usd_rub: float = float(_env("USD_RUB", "82"))
    gigachat_rub_per_1k_tokens: float = float(_env("GIGACHAT_RUB_PER_1K", "1.5"))


config = Config()
