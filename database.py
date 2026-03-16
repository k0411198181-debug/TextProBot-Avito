from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

import aiosqlite

from config import settings

UTC = timezone.utc


def utcnow() -> datetime:
    return datetime.now(UTC)


class Database:
    def __init__(self, path: str) -> None:
        self.path = path

    async def init(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(
                """
                PRAGMA journal_mode=WAL;

                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    registered_at TEXT NOT NULL,
                    ref_by INTEGER,
                    free_avito_used INTEGER NOT NULL DEFAULT 0,
                    free_youtube_used INTEGER NOT NULL DEFAULT 0,
                    free_tg_used INTEGER NOT NULL DEFAULT 0,
                    free_ig_used INTEGER NOT NULL DEFAULT 0,
                    bonus_generations INTEGER NOT NULL DEFAULT 0,
                    referral_count INTEGER NOT NULL DEFAULT 0,
                    plan TEXT NOT NULL DEFAULT 'free',
                    plan_expires_at TEXT,
                    total_generations INTEGER NOT NULL DEFAULT 0,
                    is_banned INTEGER NOT NULL DEFAULT 0,
                    spam_violations INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS generations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    input_data TEXT NOT NULL,
                    result TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                );

                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    amount INTEGER NOT NULL,
                    currency TEXT NOT NULL,
                    plan TEXT NOT NULL,
                    method TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                );

                CREATE TABLE IF NOT EXISTS promo_codes (
                    code TEXT PRIMARY KEY,
                    plan TEXT NOT NULL,
                    days INTEGER NOT NULL,
                    max_uses INTEGER NOT NULL,
                    used_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS referrals (
                    referrer_id INTEGER NOT NULL,
                    referred_id INTEGER NOT NULL UNIQUE,
                    bonus_given INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                """
            )
            await db.commit()

    async def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = await cur.fetchone()
            return dict(row) if row else None

    async def create_user(self, user_id: int, username: str, full_name: str, ref_by: int | None = None) -> None:
        registered_at = utcnow().isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO users (user_id, username, full_name, registered_at, ref_by)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, username, full_name, registered_at, ref_by),
            )
            if ref_by and ref_by != user_id:
                await db.execute(
                    "INSERT OR IGNORE INTO referrals (referrer_id, referred_id, created_at) VALUES (?, ?, ?)",
                    (ref_by, user_id, registered_at),
                )
                await db.execute(
                    "UPDATE users SET bonus_generations = bonus_generations + 3, referral_count = referral_count + 1 WHERE user_id = ?",
                    (ref_by,),
                )
            await db.commit()

    async def update_user_profile(self, user_id: int, username: str, full_name: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE users SET username = ?, full_name = ? WHERE user_id = ?",
                (username, full_name, user_id),
            )
            await db.commit()

    async def increment_spam_violation(self, user_id: int) -> int:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE users SET spam_violations = spam_violations + 1 WHERE user_id = ?",
                (user_id,),
            )
            await db.commit()
            cur = await db.execute("SELECT spam_violations FROM users WHERE user_id = ?", (user_id,))
            row = await cur.fetchone()
            return int(row[0]) if row else 0

    async def reset_spam_violations(self, user_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE users SET spam_violations = 0 WHERE user_id = ?", (user_id,))
            await db.commit()

    async def ban_user(self, user_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (user_id,))
            await db.commit()

    async def activate_plan(self, user_id: int, plan: str, days: int) -> str:
        now = utcnow()
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT plan_expires_at FROM users WHERE user_id = ?", (user_id,))
            row = await cur.fetchone()
            base = now
            if row and row[0]:
                try:
                    current_expiry = datetime.fromisoformat(row[0])
                    if current_expiry > now:
                        base = current_expiry
                except ValueError:
                    pass
            expires_at = (base + timedelta(days=days)).isoformat()
            await db.execute(
                "UPDATE users SET plan = ?, plan_expires_at = ? WHERE user_id = ?",
                (plan, expires_at, user_id),
            )
            await db.commit()
            return expires_at

    async def create_payment(self, user_id: int, amount: int, currency: str, plan: str, method: str, status: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO payments (user_id, amount, currency, plan, method, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, amount, currency, plan, method, status, utcnow().isoformat()),
            )
            await db.commit()

    async def add_generation(self, user_id: int, kind: str, input_data: Dict[str, Any], result: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO generations (user_id, type, input_data, result, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, kind, json.dumps(input_data, ensure_ascii=False), result, utcnow().isoformat()),
            )
            await db.execute(
                "UPDATE users SET total_generations = total_generations + 1 WHERE user_id = ?",
                (user_id,),
            )
            await db.commit()

    async def list_generations(self, user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM generations WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            )
            rows = await cur.fetchall()
            return [dict(row) for row in rows]

    async def get_generation(self, generation_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM generations WHERE id = ? AND user_id = ?",
                (generation_id, user_id),
            )
            row = await cur.fetchone()
            return dict(row) if row else None

    async def count_users(self) -> int:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("SELECT COUNT(*) FROM users")
            row = await cur.fetchone()
            return int(row[0])

    async def count_paid_users(self) -> int:
        now = utcnow().isoformat()
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "SELECT COUNT(*) FROM users WHERE plan != 'free' AND plan_expires_at IS NOT NULL AND plan_expires_at > ?",
                (now,),
            )
            row = await cur.fetchone()
            return int(row[0])

    async def list_user_ids(self) -> List[int]:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("SELECT user_id FROM users WHERE is_banned = 0")
            rows = await cur.fetchall()
            return [int(r[0]) for r in rows]

    async def save_promo(self, code: str, plan: str, days: int, max_uses: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO promo_codes (code, plan, days, max_uses, used_count, created_at) VALUES (?, ?, ?, ?, COALESCE((SELECT used_count FROM promo_codes WHERE code = ?), 0), ?)",
                (code.upper(), plan, days, max_uses, code.upper(), utcnow().isoformat()),
            )
            await db.commit()

    async def apply_promo(self, user_id: int, code: str) -> tuple[bool, str]:
        code = code.upper().strip()
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM promo_codes WHERE code = ?", (code,))
            row = await cur.fetchone()
            if not row:
                return False, "Промокод не найден."
            promo = dict(row)
            if promo["used_count"] >= promo["max_uses"]:
                return False, "Промокод уже исчерпан."
            await db.execute(
                "UPDATE promo_codes SET used_count = used_count + 1 WHERE code = ?",
                (code,),
            )
            await db.commit()
        await self.activate_plan(user_id, promo["plan"], promo["days"])
        return True, f"Промокод применён: {promo['plan'].upper()} на {promo['days']} дн."

    async def get_daily_count(self, user_id: int, kind: str) -> int:
        start_of_day = utcnow().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "SELECT COUNT(*) FROM generations WHERE user_id = ? AND type = ? AND created_at >= ?",
                (user_id, kind, start_of_day),
            )
            row = await cur.fetchone()
            return int(row[0])

    async def is_plan_active(self, user: Dict[str, Any]) -> bool:
        if user["plan"] == "free" or not user["plan_expires_at"]:
            return False
        try:
            return datetime.fromisoformat(user["plan_expires_at"]) > utcnow()
        except ValueError:
            return False

    async def consume_free_if_possible(self, user_id: int, kind: str) -> bool:
        field_map = {
            "avito": "free_avito_used",
            "youtube": "free_youtube_used",
            "tg": "free_tg_used",
            "ig": "free_ig_used",
        }
        field = field_map[kind]
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(f"SELECT {field}, bonus_generations FROM users WHERE user_id = ?", (user_id,))
            row = await cur.fetchone()
            if not row:
                return False
            if int(row[0]) == 0:
                await db.execute(f"UPDATE users SET {field} = 1 WHERE user_id = ?", (user_id,))
                await db.commit()
                return True
            if int(row[1]) > 0:
                await db.execute(
                    "UPDATE users SET bonus_generations = bonus_generations - 1 WHERE user_id = ?",
                    (user_id,),
                )
                await db.commit()
                return True
            return False

    async def check_access(self, user_id: int, kind: str, premium_feature: bool = False) -> tuple[bool, str]:
        user = await self.get_user(user_id)
        if not user:
            return False, "Сначала нажми /start"
        if user["is_banned"]:
            return False, "Твой доступ ограничен. Напиши в поддержку."
        plan = user["plan"]
        active = await self.is_plan_active(user)
        if active:
            limits = settings.plan_limits.get(plan, settings.plan_limits["free"])
            if premium_feature and not limits["ab_test"]:
                return False, "Эта функция доступна только в Pro и Max."
            daily_limit = int(limits[kind])
            today_count = await self.get_daily_count(user_id, kind)
            if today_count >= daily_limit:
                return False, f"Лимит на сегодня исчерпан: {today_count}/{daily_limit}. Продли тариф или приходи завтра."
            return True, "ok"
        if premium_feature:
            return False, "Эта функция только по подписке."
        free_ok = await self.consume_free_if_possible(user_id, kind)
        if free_ok:
            return True, "ok"
        return False, "Бесплатный лимит закончился. Открой тарифы и продолжай без ограничений."


DB = Database(settings.db_path)
