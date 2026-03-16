from __future__ import annotations

import time
from collections import defaultdict
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from config import settings
from database import DB
from texts import SPAM_WARNING


class RateLimitMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        self.last_seen: dict[int, float] = defaultdict(float)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        now = time.monotonic()
        last = self.last_seen[user.id]
        if now - last < settings.rate_limit_seconds:
            msg = event.message if isinstance(event, CallbackQuery) else event
            if isinstance(msg, Message):
                await msg.answer(SPAM_WARNING)
            else:
                await event.answer(SPAM_WARNING, show_alert=False)
            violations = await DB.increment_spam_violation(user.id)
            if violations >= 3:
                await DB.ban_user(user.id)
            return None

        self.last_seen[user.id] = now
        await DB.reset_spam_violations(user.id)
        return await handler(event, data)


class GenerationCooldownMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        self.last_generation: dict[int, float] = defaultdict(float)

    def touch(self, user_id: int) -> bool:
        now = time.monotonic()
        last = self.last_generation[user_id]
        if now - last < settings.generation_cooldown_seconds:
            return False
        self.last_generation[user_id] = now
        return True
