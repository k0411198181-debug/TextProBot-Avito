from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime
from typing import Any
from urllib.parse import quote_plus

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    PreCheckoutQuery,
)

from ai import AIError, generate_text
from config import settings
from database import DB
from keyboards import (
    avito_actions_inline,
    avito_followup_inline,
    history_inline,
    main_menu,
    onboarding_keyboard,
    paywall_inline,
    submenu_keyboard,
    tariffs_inline,
)
from payments import send_stars_invoice, yoomoney_text
from texts import (
    ADMIN_ONLY,
    BANNED_TEXT,
    COOLDOWN_WARNING,
    EXAMPLE_AVITO_QUESTIONS,
    EXAMPLE_IG_QUESTIONS,
    EXAMPLE_TG_QUESTIONS,
    EXAMPLE_YT_QUESTIONS,
    HELP_TEXT,
    HOW_IT_WORKS,
    PAYWALL_TEMPLATE,
    PLAN_BOUGHT,
    PROFILE_TEMPLATE,
    TARIFFS_TEXT,
    WELCOME_1,
    WELCOME_2,
    WELCOME_3,
)

router = Router()
logger = logging.getLogger(__name__)

# Fallback на твой ID, если окружение на хостинге не подхватилось.
FALLBACK_ADMIN_IDS = {6671200724}

AVITO_MENU = [
    "✍️ Создать объявление",
    "✨ Улучшить мой текст",
    "💬 Ответы покупателям",
    "🛡️ Анти-торг / анти-возражения",
    "📋 Шаблоны по нишам",
    "⚡ Быстрый сценарий",
]
YOUTUBE_MENU = [
    "🏷️ Заголовок",
    "📝 Описание",
    "🏷 Теги + SEO-ключи",
    "📦 SEO-комплект",
    "🔀 A/B-тест",
    "🎣 Хук / первая фраза",
]
TG_MENU = ["📣 Пост для канала", "🛍️ Продающий пост", "📌 Закреплённое сообщение", "🔄 3 варианта поста"]
IG_MENU = ["📸 Пост для ленты", "🎯 Рилс-подпись", "#️⃣ Хэштеги", "🛍️ Продающий пост"]

SCORE_RE = re.compile(r"(\d{1,2})\s*/\s*10")


class GenerationCooldown:
    def __init__(self) -> None:
        self.last_generation: dict[int, float] = {}

    def touch(self, user_id: int) -> bool:
        now = time.monotonic()
        last = self.last_generation.get(user_id, 0.0)
        if now - last < settings.generation_cooldown_seconds:
            return False
        self.last_generation[user_id] = now
        return True


cooldown = GenerationCooldown()


class Form(StatesGroup):
    avito_create = State()
    avito_improve = State()
    avito_anti = State()
    youtube_common = State()
    tg_common = State()
    ig_common = State()
    promo = State()


# ---------- common helpers ----------

def is_admin(user_id: int) -> bool:
    return user_id in set(settings.admin_ids) | FALLBACK_ADMIN_IDS


def extract_score(text: str) -> int:
    match = SCORE_RE.search(text or "")
    if match:
        value = int(match.group(1))
        return max(1, min(10, value))
    return 8


def ref_link_for_user(user_id: int) -> str:
    username = settings.bot_username or "your_bot"
    return f"https://t.me/{username}?start=ref_{user_id}"


def share_text_for_user(user_id: int) -> str:
    return (
        "🔥 TextPro Bot помогает делать продающие объявления для Avito, SEO для YouTube, "
        "посты для Telegram и тексты для Instagram. Попробуй: "
        f"{ref_link_for_user(user_id)}"
    )


def share_inline(user_id: int) -> InlineKeyboardMarkup:
    ref_link = ref_link_for_user(user_id)
    share_text = quote_plus(
        "🤖 Попробуй TextPro Bot — объявления для Avito, SEO для YouTube и посты для соцсетей за минуту."
    )
    share_url = f"https://t.me/share/url?url={quote_plus(ref_link)}&text={share_text}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📤 Поделиться ботом", url=share_url)],
            [InlineKeyboardButton(text="🎟️ Ввести промокод", callback_data="promo_start")],
            [InlineKeyboardButton(text="💎 Тарифы", callback_data="show_tariffs")],
        ]
    )


def ref_inline(user_id: int) -> InlineKeyboardMarkup:
    ref_link = ref_link_for_user(user_id)
    share_text = quote_plus(
        "🤖 Попробуй TextPro Bot — объявления для Avito, SEO для YouTube и посты для соцсетей за минуту."
    )
    share_url = f"https://t.me/share/url?url={quote_plus(ref_link)}&text={share_text}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📤 Поделиться ботом", url=share_url)],
            [InlineKeyboardButton(text="👤 Профиль", callback_data="open_profile")],
            [InlineKeyboardButton(text="🏠 В меню", callback_data="go_main")],
        ]
    )


async def show_main_menu(message: Message, text: str = "Выбери модуль 👇") -> None:
    await message.answer(text, reply_markup=main_menu())


async def ensure_user(message: Message, command: CommandObject | None = None) -> dict[str, Any] | None:
    user = await DB.get_user(message.from_user.id)
    if user:
        await DB.update_user_profile(
            user_id=message.from_user.id,
            username=message.from_user.username or "",
            full_name=message.from_user.full_name,
        )
        return await DB.get_user(message.from_user.id)

    ref_by = None
    if command and command.args and command.args.startswith("ref_"):
        try:
            ref_by = int(command.args.replace("ref_", "").strip())
        except ValueError:
            ref_by = None
    await DB.create_user(
        user_id=message.from_user.id,
        username=message.from_user.username or "",
        full_name=message.from_user.full_name,
        ref_by=ref_by,
    )
    return await DB.get_user(message.from_user.id)


async def ensure_user_by_id(message: Message) -> dict[str, Any] | None:
    return await ensure_user(message)


async def check_ban(message: Message) -> bool:
    user = await DB.get_user(message.from_user.id)
    if user and user["is_banned"]:
        await message.answer(BANNED_TEXT)
        return True
    return False


async def require_generation_slot(message: Message) -> bool:
    if not cooldown.touch(message.from_user.id):
        await message.answer(COOLDOWN_WARNING)
        return False
    return True


async def maybe_show_paywall(message: Message, user_id: int, score: int) -> None:
    user = await DB.get_user(user_id)
    if user and user["plan"] == "free":
        await message.answer(PAYWALL_TEMPLATE.format(score=score), reply_markup=paywall_inline())


async def send_profile(message: Message) -> None:
    await ensure_user_by_id(message)
    user = await DB.get_user(message.from_user.id)
    if not user:
        await message.answer("Не удалось открыть профиль. Нажми /start ещё раз.")
        return
    expires = user["plan_expires_at"] or "—"
    await message.answer(
        PROFILE_TEMPLATE.format(
            user_id=message.from_user.id,
            plan=user["plan"].upper(),
            expires=expires,
            total=user["total_generations"],
            bonus=user["bonus_generations"],
            refs=user["referral_count"],
            ref_link=ref_link_for_user(message.from_user.id),
        ),
        reply_markup=share_inline(message.from_user.id),
    )


async def send_ref(message: Message) -> None:
    await ensure_user_by_id(message)
    ref_link = ref_link_for_user(message.from_user.id)
    text = (
        "🔗 <b>Твоя реферальная ссылка</b>\n\n"
        f"<code>{ref_link}</code>\n\n"
        "За каждого нового пользователя ты получаешь +3 бонусные генерации."
    )
    await message.answer(text, reply_markup=ref_inline(message.from_user.id))


async def send_avito_followup_prompt(message: Message) -> None:
    await message.answer(
        "Хочешь дожать результат ещё сильнее? 👇\n\n"
        "🛡️ Анти-торг\n"
        "🧟 Пожиратели времени\n"
        "💬 FAQ покупателям\n"
        "🚚 Привезти / показать\n"
        "✨ Добавить эмоджи\n"
        "💎 Усилить продажу",
        reply_markup=avito_followup_inline(),
    )


async def run_generation(
    message: Message,
    state: FSMContext,
    access_kind: str,
    ai_kind: str,
    payload: dict[str, Any],
    premium_feature: bool = False,
    inline: InlineKeyboardMarkup | None = None,
) -> str | None:
    await ensure_user_by_id(message)
    if await check_ban(message):
        return None
    if not await require_generation_slot(message):
        return None

    allowed, reason = await DB.check_access(message.from_user.id, access_kind, premium_feature=premium_feature)
    if not allowed:
        await message.answer(reason, reply_markup=tariffs_inline())
        return None

    wait = await message.answer("⏳ Генерирую... Обычно это занимает 10–30 секунд.")
    try:
        result = await generate_text(ai_kind, payload)
    except AIError as exc:
        logger.exception("AI error")
        await wait.edit_text(f"Ошибка AI: {exc}")
        return None
    except Exception as exc:
        logger.exception("Unexpected generation error")
        await wait.edit_text(f"Неожиданная ошибка: {exc}")
        return None

    await DB.add_generation(message.from_user.id, access_kind, payload, result)
    await state.update_data(
        last_result=result,
        last_payload=payload,
        last_ai_kind=ai_kind,
        last_access_kind=access_kind,
    )
    await wait.edit_text(result, reply_markup=inline)
    await maybe_show_paywall(message, message.from_user.id, extract_score(result))
    return result


async def dispatch_text_command(message: Message, state: FSMContext) -> bool:
    text = (message.text or "").strip()
    if not text.startswith("/"):
        return False

    cmd = text.split()[0].split("@")[0].lower()
    if cmd == "/menu":
        await state.clear()
        await ensure_user_by_id(message)
        await show_main_menu(message)
        return True
    if cmd == "/avito":
        await ensure_user_by_id(message)
        await message.answer("🛒 <b>Avito</b>", reply_markup=submenu_keyboard(AVITO_MENU))
        return True
    if cmd == "/youtube":
        await ensure_user_by_id(message)
        await message.answer("▶️ <b>YouTube</b>", reply_markup=submenu_keyboard(YOUTUBE_MENU))
        return True
    if cmd == "/telegram":
        await ensure_user_by_id(message)
        await message.answer("📢 <b>Telegram</b>", reply_markup=submenu_keyboard(TG_MENU))
        return True
    if cmd == "/instagram":
        await ensure_user_by_id(message)
        await message.answer("📸 <b>Instagram</b>", reply_markup=submenu_keyboard(IG_MENU))
        return True
    if cmd == "/history":
        await ensure_user_by_id(message)
        items = await DB.list_generations(message.from_user.id, limit=10)
        if not items:
            await message.answer("История пока пустая.")
        else:
            pairs = [(item["id"], item["type"]) for item in items]
            await message.answer("📁 Последние генерации:", reply_markup=history_inline(pairs))
        return True
    if cmd == "/profile":
        await send_profile(message)
        return True
    if cmd == "/tariffs":
        await message.answer(TARIFFS_TEXT, reply_markup=tariffs_inline())
        return True
    if cmd == "/help":
        await message.answer(HELP_TEXT)
        return True
    if cmd == "/promo":
        await ensure_user_by_id(message)
        await state.set_state(Form.promo)
        await message.answer("Отправь промокод одним сообщением.")
        return True
    if cmd == "/ref":
        await send_ref(message)
        return True
    return False


# ---------- start / navigation ----------

@router.message(Command("start"))
async def start_handler(message: Message, command: CommandObject, state: FSMContext) -> None:
    user = await ensure_user(message, command)
    await state.clear()
    if not user:
        await message.answer("Не удалось создать пользователя.")
        return

    referred_by = None
    if command.args and command.args.startswith("ref_"):
        try:
            referred_by = int(command.args.replace("ref_", "").strip())
        except ValueError:
            referred_by = None
    if referred_by and referred_by != message.from_user.id and user["registered_at"] == user["registered_at"]:
        await message.answer("🎁 Реферальный код учтён, если это был твой первый запуск.")

    if user["total_generations"] == 0:
        await message.answer(WELCOME_1, reply_markup=main_menu())
        await message.answer(WELCOME_2, reply_markup=onboarding_keyboard(2))
        await message.answer(WELCOME_3, reply_markup=onboarding_keyboard(3))
    else:
        await show_main_menu(message, "С возвращением. Выбирай, что делаем 👇")


@router.callback_query(F.data == "onb_2")
async def onb_2(callback: CallbackQuery) -> None:
    await callback.message.answer(WELCOME_2, reply_markup=onboarding_keyboard(2))
    await callback.answer()


@router.callback_query(F.data == "onb_3")
async def onb_3(callback: CallbackQuery) -> None:
    await callback.message.answer(WELCOME_3, reply_markup=onboarding_keyboard(3))
    await callback.answer()


@router.callback_query(F.data.in_({"onb_try", "go_main"}))
async def onb_try(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer(HOW_IT_WORKS, reply_markup=main_menu())
    await callback.answer()


@router.message(Command("menu"))
async def menu_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    await ensure_user_by_id(message)
    await show_main_menu(message)


@router.message(Command("avito"))
@router.message(F.text == "🛒 Avito")
async def avito_menu_handler(message: Message) -> None:
    await ensure_user_by_id(message)
    await message.answer("🛒 <b>Avito</b>", reply_markup=submenu_keyboard(AVITO_MENU))


@router.message(Command("youtube"))
@router.message(F.text == "▶️ YouTube")
async def youtube_menu_handler(message: Message) -> None:
    await ensure_user_by_id(message)
    await message.answer("▶️ <b>YouTube</b>", reply_markup=submenu_keyboard(YOUTUBE_MENU))


@router.message(Command("telegram"))
@router.message(F.text == "📢 Telegram")
async def tg_menu_handler(message: Message) -> None:
    await ensure_user_by_id(message)
    await message.answer("📢 <b>Telegram</b>", reply_markup=submenu_keyboard(TG_MENU))


@router.message(Command("instagram"))
@router.message(F.text == "📸 Instagram")
async def ig_menu_handler(message: Message) -> None:
    await ensure_user_by_id(message)
    await message.answer("📸 <b>Instagram</b>", reply_markup=submenu_keyboard(IG_MENU))


@router.message(Command("tariffs"))
@router.message(F.text == "💎 Тарифы")
@router.callback_query(F.data == "show_tariffs")
async def tariffs_handler(event: Message | CallbackQuery) -> None:
    target = event.message if isinstance(event, CallbackQuery) else event
    await target.answer(TARIFFS_TEXT, reply_markup=tariffs_inline())
    if isinstance(event, CallbackQuery):
        await event.answer()


@router.message(Command("help"))
@router.message(F.text == "❓ Помощь")
async def help_handler(message: Message) -> None:
    await ensure_user_by_id(message)
    await message.answer(HELP_TEXT)


@router.message(Command("profile"))
@router.message(F.text == "👤 Профиль")
async def profile_handler(message: Message) -> None:
    await send_profile(message)


@router.callback_query(F.data == "open_profile")
async def open_profile_callback(callback: CallbackQuery) -> None:
    fake_message = callback.message
    await send_profile(fake_message)
    await callback.answer()


@router.message(Command("history"))
@router.message(F.text == "📁 История")
async def history_handler(message: Message) -> None:
    await ensure_user_by_id(message)
    items = await DB.list_generations(message.from_user.id, limit=10)
    if not items:
        await message.answer("История пока пустая.")
        return
    pairs = [(item["id"], item["type"]) for item in items]
    await message.answer("📁 Последние генерации:", reply_markup=history_inline(pairs))


@router.callback_query(F.data.startswith("history:"))
async def history_open(callback: CallbackQuery) -> None:
    generation_id = int(callback.data.split(":")[1])
    item = await DB.get_generation(generation_id, callback.from_user.id)
    if not item:
        await callback.answer("Не найдено", show_alert=True)
        return
    await callback.message.answer(item["result"])
    await callback.answer()


@router.message(F.text == "🔙 Назад")
async def back_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    await show_main_menu(message)


# ---------- Avito ----------

@router.message(F.text == "✍️ Создать объявление")
async def avito_create_start(message: Message, state: FSMContext) -> None:
    await ensure_user_by_id(message)
    await state.set_state(Form.avito_create)
    await message.answer(EXAMPLE_AVITO_QUESTIONS)


@router.message(F.text == "✨ Улучшить мой текст")
async def avito_improve_start(message: Message, state: FSMContext) -> None:
    await ensure_user_by_id(message)
    await state.set_state(Form.avito_improve)
    await message.answer("Вставь свой черновик объявления одним сообщением. Я улучшу его и усилю продажу.")


@router.message(F.text.in_({"💬 Ответы покупателям", "🛡️ Анти-торг / анти-возражения"}))
async def avito_anti_start(message: Message, state: FSMContext) -> None:
    await ensure_user_by_id(message)
    await state.set_state(Form.avito_anti)
    await message.answer(
        "Опиши товар, цену и типичные вопросы покупателей одним сообщением.\n\n"
        "Пример: iPhone 13, цена 50 000, часто пишут 'дорого', 'последняя цена?', 'отдашь за 30?', 'привези к метро'."
    )


@router.message(F.text == "📋 Шаблоны по нишам")
async def avito_templates(message: Message) -> None:
    await ensure_user_by_id(message)
    await message.answer(
        "📋 Ниши для MVP:\n• авто\n• недвижимость\n• электроника\n• мебель\n• услуги\n\n"
        "Для каждой ниши используй режим «Создать объявление» и в первом пункте укажи нишу."
    )


@router.message(F.text == "⚡ Быстрый сценарий")
async def avito_quick(message: Message, state: FSMContext) -> None:
    await ensure_user_by_id(message)
    await state.set_state(Form.avito_create)
    await message.answer(
        "Напиши коротко в таком виде:\n"
        "товар | цена | состояние | сценарий\n\n"
        "Например:\n"
        "iPhone 13 128GB | 52000 | отличное | срочно продать"
    )


@router.message(Form.avito_create)
async def avito_create_finish(message: Message, state: FSMContext) -> None:
    payload = {"user_request": message.text, "platform": "Avito"}
    result = await run_generation(message, state, "avito", "avito_create", payload, inline=avito_actions_inline())
    await state.set_state(None)
    if result:
        await send_avito_followup_prompt(message)


@router.message(Form.avito_improve)
async def avito_improve_finish(message: Message, state: FSMContext) -> None:
    payload = {"draft": message.text, "platform": "Avito", "task": "improve"}
    result = await run_generation(message, state, "avito", "avito_improve", payload, premium_feature=False)
    await state.set_state(None)
    if result:
        await send_avito_followup_prompt(message)


@router.message(Form.avito_anti)
async def avito_anti_finish(message: Message, state: FSMContext) -> None:
    payload = {"topic": message.text, "task": "faq_and_anti"}
    await run_generation(message, state, "avito", "avito_anti", payload)
    await state.set_state(None)


@router.callback_query(F.data.startswith("regen:"))
async def regenerate_avito(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    last_result = data.get("last_result")
    if not last_result:
        await callback.answer("Сначала сделай генерацию", show_alert=True)
        return
    if not cooldown.touch(callback.from_user.id):
        await callback.answer("Подожди немного и попробуй снова.", show_alert=True)
        return
    mode = callback.data.split(":", 1)[1]
    allowed, reason = await DB.check_access(callback.from_user.id, "avito")
    if not allowed:
        await callback.message.answer(reason, reply_markup=tariffs_inline())
        await callback.answer()
        return
    msg = await callback.message.answer("⏳ Перегенерирую...")
    try:
        result = await generate_text("avito_regen", {"mode": mode, "source_text": last_result})
    except Exception as exc:
        logger.exception("regen error")
        await msg.edit_text(f"Ошибка: {exc}")
        await callback.answer()
        return
    await DB.add_generation(callback.from_user.id, "avito", {"regen_mode": mode}, result)
    await state.update_data(last_result=result)
    await msg.edit_text(result, reply_markup=avito_actions_inline())
    await callback.message.answer("Хочешь ещё дожать результат? 👇", reply_markup=avito_followup_inline())
    await callback.answer("Готово")


@router.callback_query(F.data.startswith("avitoextra:"))
async def avito_followup_callback(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    source_text = data.get("last_result")
    if not source_text:
        await callback.answer("Сначала сделай объявление или улучши текст", show_alert=True)
        return
    if not cooldown.touch(callback.from_user.id):
        await callback.answer("Подожди немного и попробуй снова.", show_alert=True)
        return

    task = callback.data.split(":", 1)[1]
    msg = await callback.message.answer("⏳ Готовлю блок...")
    try:
        result = await generate_text("avito_followup", {"task": task, "source_text": source_text})
    except Exception as exc:
        logger.exception("avito followup error")
        await msg.edit_text(f"Ошибка: {exc}")
        await callback.answer()
        return

    await DB.add_generation(callback.from_user.id, "avito", {"task": task, "source_text": source_text}, result)
    await state.update_data(last_followup_task=task, last_followup_result=result)
    await msg.edit_text(result, reply_markup=avito_followup_inline())
    await callback.answer("Готово")


# ---------- YouTube / Telegram / Instagram ----------

@router.message(F.text.in_(set(YOUTUBE_MENU)))
async def youtube_start(message: Message, state: FSMContext) -> None:
    await ensure_user_by_id(message)
    task_map = {
        "🏷️ Заголовок": "title",
        "📝 Описание": "description",
        "🏷 Теги + SEO-ключи": "tags",
        "📦 SEO-комплект": "pack",
        "🔀 A/B-тест": "ab",
        "🎣 Хук / первая фраза": "hook",
    }
    await state.set_state(Form.youtube_common)
    await state.update_data(youtube_task=task_map[message.text])
    await message.answer(EXAMPLE_YT_QUESTIONS)


@router.message(Form.youtube_common)
async def youtube_finish(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    task = data.get("youtube_task", "pack")
    premium = task == "ab"
    ai_kind = "youtube_ab" if task == "ab" else "youtube_pack"
    payload = {"task": task, "user_request": message.text, "platform": "YouTube"}
    await run_generation(message, state, "youtube", ai_kind, payload, premium_feature=premium)
    await state.set_state(None)


@router.message(F.text.in_(set(TG_MENU)))
async def tg_start(message: Message, state: FSMContext) -> None:
    await ensure_user_by_id(message)
    premium = message.text == "🔄 3 варианта поста"
    await state.set_state(Form.tg_common)
    await state.update_data(tg_premium=premium, tg_task=message.text)
    await message.answer(EXAMPLE_TG_QUESTIONS)


@router.message(Form.tg_common)
async def tg_finish(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    payload = {"task": data.get("tg_task"), "user_request": message.text, "platform": "Telegram"}
    await run_generation(message, state, "tg", "tg_post", payload, premium_feature=bool(data.get("tg_premium")))
    await state.set_state(None)


@router.message(F.text.in_(set(IG_MENU)))
async def ig_start(message: Message, state: FSMContext) -> None:
    await ensure_user_by_id(message)
    await state.set_state(Form.ig_common)
    await state.update_data(ig_task=message.text)
    await message.answer(EXAMPLE_IG_QUESTIONS)


@router.message(Form.ig_common)
async def ig_finish(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    payload = {"task": data.get("ig_task"), "user_request": message.text, "platform": "Instagram"}
    await run_generation(message, state, "ig", "ig_post", payload)
    await state.set_state(None)


# ---------- Promo / referrals ----------

@router.message(Command("promo"))
@router.callback_query(F.data == "promo_start")
@router.message(F.text == "🎟️ Ввести промокод")
async def promo_start(event: Message | CallbackQuery, state: FSMContext) -> None:
    target = event.message if isinstance(event, CallbackQuery) else event
    await ensure_user_by_id(target)
    await state.set_state(Form.promo)
    await target.answer("Отправь промокод одним сообщением.")
    if isinstance(event, CallbackQuery):
        await event.answer()


@router.message(Form.promo)
async def promo_finish(message: Message, state: FSMContext) -> None:
    await ensure_user_by_id(message)
    ok, result = await DB.apply_promo(message.from_user.id, message.text)
    await message.answer(result)
    await state.set_state(None)


@router.message(Command("ref"))
async def ref_command(message: Message) -> None:
    await send_ref(message)


# ---------- Payments ----------

@router.callback_query(F.data.startswith("buy_"))
async def buy_plan(callback: CallbackQuery) -> None:
    await ensure_user_by_id(callback.message)
    action = callback.data.replace("buy_", "")
    if action == "yoomoney":
        await callback.message.answer(yoomoney_text())
        await callback.answer()
        return
    if action not in settings.plan_days:
        await callback.answer("Неизвестный тариф", show_alert=True)
        return
    await send_stars_invoice(callback.message, action)
    await callback.answer()


@router.pre_checkout_query()
async def pre_checkout(pre_checkout_query: PreCheckoutQuery) -> None:
    await pre_checkout_query.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment(message: Message) -> None:
    payload = message.successful_payment.invoice_payload
    try:
        _, plan, user_id = payload.split(":")
        user_id = int(user_id)
    except ValueError:
        await message.answer("Оплата прошла, но payload не распознан.")
        return
    expires_at = await DB.activate_plan(user_id, plan, settings.plan_days[plan])
    await DB.create_payment(user_id, settings.plan_prices_stars[plan], "XTR", plan, "stars", "paid")
    expires = datetime.fromisoformat(expires_at).strftime("%d.%m.%Y %H:%M UTC")
    await message.answer(PLAN_BOUGHT.format(plan=plan.upper(), expires=expires), reply_markup=main_menu())


# ---------- Admin ----------

@router.message(Command("stats"))
async def stats_command(message: Message) -> None:
    if not is_admin(message.from_user.id):
        await message.answer(ADMIN_ONLY)
        return
    users = await DB.count_users()
    paid = await DB.count_paid_users()
    await message.answer(
        f"📊 Пользователей: <b>{users}</b>\n"
        f"Платящих: <b>{paid}</b>\n"
        f"Твой ID: <code>{message.from_user.id}</code>"
    )


@router.message(Command("premium_add"))
async def premium_add(message: Message, command: CommandObject) -> None:
    if not is_admin(message.from_user.id):
        await message.answer(ADMIN_ONLY)
        return
    parts = (command.args or "").split()
    if len(parts) not in (2, 3):
        await message.answer("Формат: /premium_add <id> <plan> [days]")
        return
    user_id = int(parts[0])
    plan = parts[1].lower()
    days = int(parts[2]) if len(parts) == 3 else settings.plan_days.get(plan, 7)
    target_user = await DB.get_user(user_id)
    if not target_user:
        await message.answer("Пользователь ещё не запускал бота. Сначала пусть нажмёт /start.")
        return
    expires_at = await DB.activate_plan(user_id, plan, days)
    await message.answer(f"Готово. {user_id} → {plan.upper()} до {expires_at}")


@router.message(Command("promo_add"))
async def promo_add(message: Message, command: CommandObject) -> None:
    if not is_admin(message.from_user.id):
        await message.answer(ADMIN_ONLY)
        return
    parts = (command.args or "").split()
    if len(parts) != 4:
        await message.answer("Формат: /promo_add <код> <plan> <days> <limit>")
        return
    code, plan, days, limit = parts[0], parts[1].lower(), int(parts[2]), int(parts[3])
    await DB.save_promo(code, plan, days, limit)
    await message.answer(f"Промокод {code.upper()} создан.")


@router.message(Command("ban"))
async def ban_cmd(message: Message, command: CommandObject) -> None:
    if not is_admin(message.from_user.id):
        await message.answer(ADMIN_ONLY)
        return
    try:
        user_id = int((command.args or "").strip())
    except ValueError:
        await message.answer("Формат: /ban <id>")
        return
    await DB.ban_user(user_id)
    await message.answer(f"Пользователь {user_id} забанен.")


@router.message(Command("broadcast"))
async def broadcast(message: Message, command: CommandObject) -> None:
    if not is_admin(message.from_user.id):
        await message.answer(ADMIN_ONLY)
        return
    text = (command.args or "").strip()
    if not text:
        await message.answer("Формат: /broadcast <текст>")
        return
    user_ids = await DB.list_user_ids()
    sent = 0
    for uid in user_ids:
        try:
            await message.bot.send_message(uid, text)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            logger.exception("Broadcast failed for %s", uid)
    await message.answer(f"Рассылка завершена. Отправлено: {sent}")


# ---------- Fallback ----------

@router.message()
async def fallback(message: Message, state: FSMContext) -> None:
    if await dispatch_text_command(message, state):
        return
    await ensure_user_by_id(message)
    await message.answer("Не понял запрос. Выбери действие из меню 👇", reply_markup=main_menu())
