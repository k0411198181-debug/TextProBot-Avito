from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery

from ai import AIError, generate_text
from config import settings
from database import DB
from keyboards import (
    avito_actions_inline,
    history_inline,
    main_menu,
    onboarding_keyboard,
    paywall_inline,
    submenu_keyboard,
    tariffs_inline,
)
from middlewares import GenerationCooldownMiddleware
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

cooldown = GenerationCooldownMiddleware()

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


class Form(StatesGroup):
    avito_create = State()
    avito_improve = State()
    avito_anti = State()
    youtube_common = State()
    tg_common = State()
    ig_common = State()
    promo = State()


def is_admin(user_id: int) -> bool:
    return user_id in settings.admin_ids


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
        return user

    ref_by = None
    if command and command.args and command.args.startswith("ref_"):
        try:
            ref_by = int(command.args.replace("ref_", ""))
        except ValueError:
            ref_by = None
    await DB.create_user(
        user_id=message.from_user.id,
        username=message.from_user.username or "",
        full_name=message.from_user.full_name,
        ref_by=ref_by,
    )
    return await DB.get_user(message.from_user.id)


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


async def run_generation(
    message: Message,
    state: FSMContext,
    access_kind: str,
    ai_kind: str,
    payload: dict[str, Any],
    premium_feature: bool = False,
    inline=None,
) -> None:
    if await check_ban(message):
        return
    if not await require_generation_slot(message):
        return

    allowed, reason = await DB.check_access(message.from_user.id, access_kind, premium_feature=premium_feature)
    if not allowed:
        await message.answer(reason, reply_markup=tariffs_inline())
        return

    wait = await message.answer("⏳ Генерирую... Обычно это занимает 10–30 секунд.")
    try:
        result = await generate_text(ai_kind, payload)
    except AIError as exc:
        logger.exception("AI error")
        await wait.edit_text(f"Ошибка AI: {exc}")
        return
    except Exception as exc:
        logger.exception("Unexpected generation error")
        await wait.edit_text(f"Неожиданная ошибка: {exc}")
        return

    await DB.add_generation(message.from_user.id, access_kind, payload, result)
    await state.update_data(last_result=result, last_payload=payload, last_ai_kind=ai_kind, last_access_kind=access_kind)
    await wait.edit_text(result, reply_markup=inline)
    score = extract_score(result)
    await maybe_show_paywall(message, message.from_user.id, score)


SCORE_RE = re.compile(r"(\d{1,2})\s*/\s*10")


def extract_score(text: str) -> int:
    match = SCORE_RE.search(text)
    if match:
        value = int(match.group(1))
        return max(1, min(10, value))
    return 8


@router.message(Command("start"))
async def start_handler(message: Message, command: CommandObject, state: FSMContext) -> None:
    user = await ensure_user(message, command)
    await state.clear()
    if not user:
        await message.answer("Не удалось создать пользователя.")
        return

    if command.args and command.args.startswith("ref_") and int(command.args.replace("ref_", "0") or 0) != message.from_user.id:
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


@router.message(F.text == "🛒 Avito")
async def avito_menu(message: Message) -> None:
    await message.answer("🛒 <b>Avito</b>", reply_markup=submenu_keyboard(AVITO_MENU))


@router.message(F.text == "▶️ YouTube")
async def youtube_menu(message: Message) -> None:
    await message.answer("▶️ <b>YouTube</b>", reply_markup=submenu_keyboard(YOUTUBE_MENU))


@router.message(F.text == "📢 Telegram")
async def tg_menu(message: Message) -> None:
    await message.answer("📢 <b>Telegram</b>", reply_markup=submenu_keyboard(TG_MENU))


@router.message(F.text == "📸 Instagram")
async def ig_menu(message: Message) -> None:
    await message.answer("📸 <b>Instagram</b>", reply_markup=submenu_keyboard(IG_MENU))


@router.message(F.text == "💎 Тарифы")
@router.callback_query(F.data == "show_tariffs")
async def tariffs_handler(event: Message | CallbackQuery) -> None:
    target = event.message if isinstance(event, CallbackQuery) else event
    await target.answer(TARIFFS_TEXT, reply_markup=tariffs_inline())
    if isinstance(event, CallbackQuery):
        await event.answer()


@router.message(F.text == "❓ Помощь")
async def help_handler(message: Message) -> None:
    await message.answer(HELP_TEXT)


@router.message(F.text == "👤 Профиль")
async def profile_handler(message: Message) -> None:
    user = await DB.get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала нажми /start")
        return
    ref_slug = settings.bot_username or "your_bot"
    ref_link = f"https://t.me/{ref_slug}?start=ref_{message.from_user.id}"
    expires = user["plan_expires_at"] or "—"
    await message.answer(
        PROFILE_TEMPLATE.format(
            user_id=message.from_user.id,
            plan=user["plan"].upper(),
            expires=expires,
            total=user["total_generations"],
            bonus=user["bonus_generations"],
            refs=user["referral_count"],
            ref_link=ref_link,
        )
    )


@router.message(F.text == "📁 История")
async def history_handler(message: Message) -> None:
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


@router.message(F.text == "✍️ Создать объявление")
async def avito_create_start(message: Message, state: FSMContext) -> None:
    await state.set_state(Form.avito_create)
    await message.answer(EXAMPLE_AVITO_QUESTIONS)


@router.message(F.text == "✨ Улучшить мой текст")
async def avito_improve_start(message: Message, state: FSMContext) -> None:
    await state.set_state(Form.avito_improve)
    await message.answer("Вставь свой черновик объявления одним сообщением. Я улучшу его и усилю продажу.")


@router.message(F.text.in_({"💬 Ответы покупателям", "🛡️ Анти-торг / анти-возражения"}))
async def avito_anti_start(message: Message, state: FSMContext) -> None:
    await state.set_state(Form.avito_anti)
    await message.answer("Опиши товар, цену и типичные вопросы покупателей одним сообщением.")


@router.message(F.text == "📋 Шаблоны по нишам")
async def avito_templates(message: Message) -> None:
    await message.answer(
        "📋 Ниши для MVP:\n• авто\n• недвижимость\n• электроника\n• мебель\n• услуги\n\n"
        "Для каждой ниши используй режим «Создать объявление» и в первом пункте укажи нишу."
    )


@router.message(F.text == "⚡ Быстрый сценарий")
async def avito_quick(message: Message, state: FSMContext) -> None:
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
    await run_generation(message, state, "avito", "avito_create", payload, inline=avito_actions_inline())
    await state.set_state(None)


@router.message(Form.avito_improve)
async def avito_improve_finish(message: Message, state: FSMContext) -> None:
    payload = {"draft": message.text, "platform": "Avito", "task": "improve"}
    await run_generation(message, state, "avito", "avito_improve", payload, premium_feature=True)
    await state.set_state(None)


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
        await msg.edit_text(f"Ошибка: {exc}")
        await callback.answer()
        return
    await DB.add_generation(callback.from_user.id, "avito", {"regen_mode": mode}, result)
    await state.update_data(last_result=result)
    await msg.edit_text(result, reply_markup=avito_actions_inline())
    await callback.answer("Готово")


@router.message(F.text.in_(set(YOUTUBE_MENU)))
async def youtube_start(message: Message, state: FSMContext) -> None:
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
    await state.set_state(Form.ig_common)
    await state.update_data(ig_task=message.text)
    await message.answer(EXAMPLE_IG_QUESTIONS)


@router.message(Form.ig_common)
async def ig_finish(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    payload = {"task": data.get("ig_task"), "user_request": message.text, "platform": "Instagram"}
    await run_generation(message, state, "ig", "ig_post", payload)
    await state.set_state(None)


@router.message(F.text == "🎟️ Ввести промокод")
async def promo_start(message: Message, state: FSMContext) -> None:
    await state.set_state(Form.promo)
    await message.answer("Отправь промокод одним сообщением.")


@router.message(Form.promo)
async def promo_finish(message: Message, state: FSMContext) -> None:
    ok, result = await DB.apply_promo(message.from_user.id, message.text)
    await message.answer(result)
    await state.set_state(None)


@router.callback_query(F.data.startswith("buy_"))
async def buy_plan(callback: CallbackQuery) -> None:
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


@router.message(Command("stats"))
async def stats_command(message: Message) -> None:
    if not is_admin(message.from_user.id):
        await message.answer(ADMIN_ONLY)
        return
    users = await DB.count_users()
    paid = await DB.count_paid_users()
    await message.answer(f"📊 Пользователей: <b>{users}</b>\nПлатящих: <b>{paid}</b>")


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


@router.message()
async def fallback(message: Message) -> None:
    await ensure_user(message)
    await message.answer("Не понял запрос. Выбери действие из меню 👇", reply_markup=main_menu())
