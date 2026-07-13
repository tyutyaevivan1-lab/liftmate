"""
Разбор свободного текста мини-опроса профиля пользователя (см. handlers.py,
states.ProfileStates) через GPT-4o-mini: "сколько месяцев/лет ты ходишь в зал?" ->
примерное число месяцев стажа. Само сохранение профиля и inline-кнопки (оборудование,
"Нет" для ограничений) — в database.py и keyboards.py соответственно.
"""

import json
import logging
from typing import Optional

from openai import AsyncOpenAI

from config import OPENAI_API_KEY

logger = logging.getLogger(__name__)

client = AsyncOpenAI(api_key=OPENAI_API_KEY)

EQUIPMENT_TYPES = ("free_weights", "machines", "full_gym", "home")

EXPERIENCE_SYSTEM_PROMPT = """Ты помогаешь определить тренировочный стаж пользователя в зале.

Пользователь свободным текстом ответил на вопрос "Сколько месяцев/лет ты уже ходишь в зал?" — ответ может быть НА ЛЮБОМ ЯЗЫКЕ и в любой форме, например: "полгода", "2 года", "только начинаю", "с детства", "since 3 months", "je m'entraine depuis 1 an", "новичок".

Верни ТОЛЬКО валидный JSON без пояснений и markdown:
{"experience_months": число_или_null}

Правила:
- Переведи ответ в ПРИМЕРНОЕ количество МЕСЯЦЕВ стажа (целое число, минимум 0).
- "только начинаю" / "just started" / "новичок" / "с нуля" -> 0.
- "с детства" / много лет без точного числа -> разумная оценка (например, 120).
- Если из текста ВООБЩЕ невозможно понять длительность (это не ответ про стаж) — верни {"experience_months": null}.
"""


async def parse_experience_months(text: str) -> Optional[int]:
    """
    Определяет примерный стаж тренировок в месяцах из свободного текста пользователя.
    Возвращает None при ошибке OpenAI или если ответ не удалось интерпретировать —
    вызывающий код и дальнейшие промпты (см. program.py) трактуют None как "неизвестно"
    и подразумевают средний уровень подготовки, не блокируя диалог.
    """
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": EXPERIENCE_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content)
        months = data.get("experience_months")
        return int(months) if months is not None else None
    except Exception:
        logger.exception("Не удалось определить стаж тренировок через OpenAI")
        return None
