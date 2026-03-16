from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List

from dotenv import load_dotenv

load_dotenv()


@dataclass(slots=True)
class Settings:
    bot_token: str = os.getenv("BOT_TOKEN", "")
    proxy_api_key: str = os.getenv("PROXY_API_KEY", "")
    proxy_api_base_url: str = os.getenv("PROXY_API_BASE_URL", "https://api.proxyapi.ru/openai/v1")
    ai_model: str = os.getenv("AI_MODEL", "gpt-4o-mini")
    admin_ids: List[int] = field(
        default_factory=lambda: [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
    )
    db_path: str = os.getenv("DB_PATH", "textpro.db")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    debug: bool = os.getenv("DEBUG", "false").lower() == "true"
    bot_username: str = os.getenv("BOT_USERNAME", "")

    start_price_stars: int = int(os.getenv("START_PRICE_STARS", "99"))
    pro_price_stars: int = int(os.getenv("PRO_PRICE_STARS", "249"))
    max_price_stars: int = int(os.getenv("MAX_PRICE_STARS", "599"))

    start_price_rub: int = int(os.getenv("START_PRICE_RUB", "149"))
    pro_price_rub: int = int(os.getenv("PRO_PRICE_RUB", "349"))
    max_price_rub: int = int(os.getenv("MAX_PRICE_RUB", "890"))

    yoomoney_enabled: bool = os.getenv("YOOMONEY_ENABLED", "false").lower() == "true"
    yoomoney_wallet: str = os.getenv("YOOMONEY_WALLET", "")
    yoomoney_quickpay_url: str = os.getenv("YOOMONEY_QUICKPAY_URL", "")

    rate_limit_seconds: float = float(os.getenv("RATE_LIMIT_SECONDS", "2"))
    generation_cooldown_seconds: float = float(os.getenv("GENERATION_COOLDOWN_SECONDS", "15"))

    @property
    def plan_limits(self) -> Dict[str, Dict[str, int | bool | None]]:
        return {
            "free": {
                "avito": 1,
                "youtube": 1,
                "tg": 1,
                "ig": 1,
                "ab_test": False,
                "history_days": 0,
            },
            "start": {
                "avito": 15,
                "youtube": 10,
                "tg": 10,
                "ig": 10,
                "ab_test": False,
                "history_days": 7,
            },
            "pro": {
                "avito": 40,
                "youtube": 30,
                "tg": 30,
                "ig": 30,
                "ab_test": True,
                "history_days": 30,
            },
            "max": {
                "avito": 100,
                "youtube": 80,
                "tg": 80,
                "ig": 80,
                "ab_test": True,
                "history_days": None,
            },
        }

    @property
    def plan_days(self) -> Dict[str, int]:
        return {"start": 1, "pro": 7, "max": 30}

    @property
    def plan_prices_stars(self) -> Dict[str, int]:
        return {"start": self.start_price_stars, "pro": self.pro_price_stars, "max": self.max_price_stars}

    @property
    def plan_prices_rub(self) -> Dict[str, int]:
        return {"start": self.start_price_rub, "pro": self.pro_price_rub, "max": self.max_price_rub}


settings = Settings()
