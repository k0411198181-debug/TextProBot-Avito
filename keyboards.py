from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from config import settings


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛒 Avito"), KeyboardButton(text="▶️ YouTube")],
            [KeyboardButton(text="📢 Telegram"), KeyboardButton(text="📸 Instagram")],
            [KeyboardButton(text="💎 Тарифы"), KeyboardButton(text="📁 История")],
            [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="❓ Помощь")],
        ],
        resize_keyboard=True,
    )


def submenu_keyboard(items: list[str]) -> ReplyKeyboardMarkup:
    rows: list[list[KeyboardButton]] = []
    current: list[KeyboardButton] = []
    for item in items:
        current.append(KeyboardButton(text=item))
        if len(current) == 2:
            rows.append(current)
            current = []
    if current:
        rows.append(current)
    rows.append([KeyboardButton(text="🔙 Назад")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def onboarding_keyboard(step: int) -> InlineKeyboardMarkup:
    if step == 1:
        buttons = [
            [InlineKeyboardButton(text="Попробовать бесплатно →", callback_data="onb_try")],
            [InlineKeyboardButton(text="Как это работает?", callback_data="onb_2")],
        ]
    elif step == 2:
        buttons = [
            [InlineKeyboardButton(text="Показать пример", callback_data="onb_3")],
            [InlineKeyboardButton(text="Попробовать →", callback_data="onb_try")],
        ]
    else:
        buttons = [
            [InlineKeyboardButton(text="Хочу такое же →", callback_data="onb_try")],
            [InlineKeyboardButton(text="Смотреть тарифы", callback_data="show_tariffs")],
        ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def back_to_main_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🏠 В меню", callback_data="go_main")]]
    )


def tariffs_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"💎 Start — {settings.start_price_stars}⭐", callback_data="buy_start")],
            [InlineKeyboardButton(text=f"🚀 Pro — {settings.pro_price_stars}⭐", callback_data="buy_pro")],
            [InlineKeyboardButton(text=f"👑 Max — {settings.max_price_stars}⭐", callback_data="buy_max")],
            [InlineKeyboardButton(text="💸 YooMoney", callback_data="buy_yoomoney")],
        ]
    )


def paywall_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"💎 Start — {settings.start_price_stars}⭐", callback_data="buy_start")],
            [InlineKeyboardButton(text=f"🚀 Pro — {settings.pro_price_stars}⭐", callback_data="buy_pro")],
            [InlineKeyboardButton(text=f"👑 Max — {settings.max_price_stars}⭐", callback_data="buy_max")],
            [InlineKeyboardButton(text="Позже", callback_data="go_main")],
        ]
    )


def history_inline(items: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text=f"#{item_id} • {kind}", callback_data=f"history:{item_id}")]
        for item_id, kind in items
    ]
    keyboard.append([InlineKeyboardButton(text="🏠 В меню", callback_data="go_main")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def avito_actions_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Сделать мягче", callback_data="regen:soft")],
            [InlineKeyboardButton(text="Сделать агрессивнее", callback_data="regen:hard")],
            [InlineKeyboardButton(text="Сделать короче", callback_data="regen:short")],
            [InlineKeyboardButton(text="Под срочную продажу", callback_data="regen:urgent")],
        ]
    )
