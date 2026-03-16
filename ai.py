from __future__ import annotations

from typing import Any, Dict

import httpx

from config import settings

BASE_PROMPT = (
    "Ты опытный русскоязычный маркетинговый копирайтер. Пиши естественно, без воды, без канцелярита. "
    "Возвращай готовый результат в структурированном виде, с понятными заголовками. "
    "Не упоминай, что ты ИИ. Пиши так, чтобы текст можно было сразу копировать."
)

PROMPTS = {
    "avito_create": (
        BASE_PROMPT
        + "\n\nСобери пакет для Авито: 3 заголовка, короткое описание, полное описание, преимущества, CTA, FAQ (5), "
        "анти-торг (6), ответы пожирателям времени (5), оценка текста по шкале 1-10 с коротким объяснением."
    ),
    "avito_improve": (
        BASE_PROMPT
        + "\n\nУлучши черновик объявления для Авито. Сделай 2 версии: короткую и сильную. Добавь 3 заголовка, преимущества, CTA и оценку /10."
    ),
    "avito_anti": (
        BASE_PROMPT
        + "\n\nСгенерируй вежливые, твёрдые ответы на торг, пустые вопросы и возражения покупателей."
    ),
    "youtube_pack": (
        BASE_PROMPT
        + "\n\nСделай YouTube SEO-комплект: 5 заголовков с разной силой клика, 2 описания, 30 тегов, SEO-ключи, хук, закреплённый комментарий, оценка /10."
    ),
    "youtube_ab": (
        BASE_PROMPT
        + "\n\nСделай платный A/B-тест: 10 заголовков, 4 описания, объясни какие пары тестировать первыми и почему."
    ),
    "tg_post": (
        BASE_PROMPT
        + "\n\nСделай 3 варианта поста для Telegram, сильный первый абзац, CTA, короткую и длинную версию, оценку /10."
    ),
    "ig_post": (
        BASE_PROMPT
        + "\n\nСделай подпись для Instagram, 30 релевантных хэштегов, короткий сценарий для рилс в 1-2 строках, CTA, оценку /10."
    ),
    "avito_regen": (
        BASE_PROMPT
        + "\n\nПерепиши готовое объявление по указанному стилю. Сохрани смысл, но усили конверсию."
    ),
}


class AIError(RuntimeError):
    pass


async def generate_text(kind: str, payload: Dict[str, Any]) -> str:
    if not settings.proxy_api_key:
        raise AIError("Не задан PROXY_API_KEY. Добавь его в переменные окружения.")

    system_prompt = PROMPTS.get(kind, BASE_PROMPT)
    user_prompt = f"Данные пользователя:\n{payload}"

    url = settings.proxy_api_base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.proxy_api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": settings.ai_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.8,
    }

    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(url, headers=headers, json=body)
        if response.status_code >= 400:
            raise AIError(f"Ошибка AI API: {response.status_code} {response.text[:300]}")
        data = response.json()

    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise AIError(f"Неожиданный ответ AI API: {data}") from exc
