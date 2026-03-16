from __future__ import annotations

from aiogram.types import LabeledPrice, Message

from config import settings
from database import DB


async def send_stars_invoice(message: Message, plan: str) -> None:
    prices = settings.plan_prices_stars
    days = settings.plan_days
    amount = prices[plan]
    await DB.create_payment(
        user_id=message.from_user.id,
        amount=amount,
        currency="XTR",
        plan=plan,
        method="stars",
        status="pending",
    )
    await message.answer_invoice(
        title=f"TextPro {plan.upper()}",
        description=f"Подписка {plan.upper()} на {days[plan]} дн.",
        payload=f"textpro:{plan}:{message.from_user.id}",
        currency="XTR",
        prices=[LabeledPrice(label=f"{plan.upper()} plan", amount=amount)],
        provider_token="",
    )


def yoomoney_text() -> str:
    if settings.yoomoney_quickpay_url:
        return (
            "💸 <b>YooMoney</b>\n\n"
            f"Открой ссылку и оплати:\n{settings.yoomoney_quickpay_url}\n\n"
            "После оплаты админ может выдать подписку командой /premium_add."
        )
    return (
        "💸 <b>YooMoney пока в режиме v2</b>\n\n"
        "В MVP оплата идёт через Telegram Stars.\n"
        "Если хочешь подключить YooMoney позже — просто добавь URL быстрой оплаты в переменную YOOMONEY_QUICKPAY_URL."
    )
