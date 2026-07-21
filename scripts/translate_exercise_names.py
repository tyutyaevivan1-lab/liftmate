"""
Одноразовый скрипт: ШАГ 2 плана по иллюстрациям упражнений — переводит name_en из
exercise_library на русский и французский (name_ru/name_fr) через GPT-4o-mini.

Берёт только записи, где name_ru IS NULL ИЛИ name_fr IS NULL — безопасно перезапускать
(уже переведённые строки не трогает и повторно не оплачивает).

Переводит БАТЧАМИ (см. BATCH_SIZE), а не по одному упражнению за вызов — 873 отдельных
вызова были бы намного медленнее и дороже. GPT просят вернуть JSON-соответствие
{exercise_id: {name_ru, name_fr}} на весь батч разом.

Промпт явно требует общепринятую фитнес-терминологию (например "Bench Press" -> "Жим
лёжа", не дословный перевод) — см. TRANSLATE_SYSTEM_PROMPT.

Запуск: python scripts/translate_exercise_names.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
import logging

from openai import AsyncOpenAI

from config import OPENAI_API_KEY
from database import close_pool, get_pool, init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("translate_exercise_names")

client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# 30 названий за вызов — достаточно, чтобы не разбивать 873 упражнения на сотни вызовов,
# но и не настолько много, чтобы GPT начал "терять" отдельные id в длинном списке
BATCH_SIZE = 30

TRANSLATE_SYSTEM_PROMPT = """Ты — профессиональный переводчик фитнес-терминологии.

Тебе дан список названий упражнений на английском языке, каждое со своим ID. Переведи
КАЖДОЕ название на русский и французский язык.

ВАЖНО:
- Это НАЗВАНИЯ УПРАЖНЕНИЙ в фитнес/бодибилдинг-контексте — переводи ОБЩЕПРИНЯТЫМИ
  терминами, которые реально использует русско- и франкоязычное сообщество качалок,
  а не дословным переводом. Например "Bench Press" -> "Жим лёжа" (НЕ "Скамейный пресс"),
  "Barbell Squat" -> "Приседания со штангой", "Lat Pulldown" -> "Тяга верхнего блока".
- Если для упражнения нет устоявшегося русского/французского термина (редкие/составные
  названия) — переведи как можно ближе по смыслу и, если нужно, добавь уточнение в
  скобках (например уточни оборудование или технику), но НЕ придумывай термин, которого
  не существует.
- РЕГИСТР: пиши название ОБЫЧНЫМ регистром (не Title Case) — заглавная буква только у
  первого слова всей фразы (плюс у имён собственных/аббревиатур, если они есть).
  Правильно: "Приседания со штангой", "Тяга верхнего блока широким хватом".
  Неправильно: "Приседания Со Штангой", "Тяга Верхнего Блока Широким Хватом".
- НЕ СМЕШИВАЙ АЛФАВИТЫ ВНУТРИ ОДНОГО СЛОВА — ни при каких обстоятельствах не получай
  слово вроде "трicepsа" (кириллица+латиница в одном слове — это всегда ошибка, а не
  осознанный выбор). Разрешено оставлять ЦЕЛИКОМ латиницей только общепринятые
  международные аббревиатуры/названия оборудования, которые так и используются в
  русской/французской речи качалок (например "SMR", "EZ-гриф", "TRX", "BOSU") — но
  даже тогда остальная часть фразы вокруг них должна быть полностью на целевом языке
  (например "SMR для икр", НЕ "SMR Икр" и НЕ частично посреди слова). Если сомневаешься —
  переведи abbreviation-often-used-as-is как есть отдельным словом, но никогда не режь
  русское/французское слово пополам латинскими буквами.
- Если название содержит малоизвестное сочетание (например "Zottman Preacher Curl") —
  переведи его как связное, грамматически правильное словосочетание на целевом языке
  (например "Сгибание рук Зоттмана на скамье Скотта"), а не набор обрывков слов.

Верни ТОЛЬКО валидный JSON без пояснений и markdown, строго такой структуры:
{
  "translations": {
    "<exercise_id ровно как во входных данных>": {"name_ru": "...", "name_fr": "..."},
    ...
  }
}

В "translations" должны быть ВСЕ id из входного списка, ни один не пропущен.
"""


def chunked(items: list, size: int) -> list:
    return [items[i : i + size] for i in range(0, len(items), size)]


async def fetch_untranslated(pool) -> list:
    rows = await pool.fetch(
        """
        SELECT exercise_id, name_en FROM exercise_library
        WHERE name_ru IS NULL OR name_fr IS NULL
        ORDER BY exercise_id
        """
    )
    return [dict(row) for row in rows]


async def translate_batch(batch: list) -> dict:
    """
    Переводит один батч [{"exercise_id":..., "name_en":...}, ...].
    Возвращает {exercise_id: {"name_ru":..., "name_fr":...}}. При ошибке OpenAI или
    некорректном JSON возвращает пустой словарь — вызывающий код пометит батч как
    непереведённый в этом прогоне (строки просто останутся NULL и попадут в следующий
    перезапуск скрипта).
    """
    payload = {"exercises": [{"id": item["exercise_id"], "name_en": item["name_en"]} for item in batch]}

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": TRANSLATE_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content)
        return data.get("translations", {})
    except Exception:
        logger.exception("Не удалось перевести батч из %d упражнений", len(batch))
        return {}


async def translate_all() -> tuple:
    await init_db()
    pool = await get_pool()

    to_translate = await fetch_untranslated(pool)
    logger.info("Найдено %d записей с непереведённым названием", len(to_translate))
    if not to_translate:
        return 0, []

    batches = chunked(to_translate, BATCH_SIZE)
    logger.info("Разбито на %d батчей по %d упражнений", len(batches), BATCH_SIZE)

    updated_count = 0
    missing_ids = []
    samples = []

    for batch_index, batch in enumerate(batches, start=1):
        logger.info("Батч %d/%d (%d упражнений)...", batch_index, len(batches), len(batch))
        translations = await translate_batch(batch)

        for item in batch:
            exercise_id = item["exercise_id"]
            translation = translations.get(exercise_id)
            if not translation or not translation.get("name_ru") or not translation.get("name_fr"):
                missing_ids.append(exercise_id)
                continue

            await pool.execute(
                "UPDATE exercise_library SET name_ru = $1, name_fr = $2 WHERE exercise_id = $3",
                translation["name_ru"].strip(),
                translation["name_fr"].strip(),
                exercise_id,
            )
            updated_count += 1
            if len(samples) < 15:
                samples.append((exercise_id, item["name_en"], translation["name_ru"], translation["name_fr"]))

    # GPT иногда пропускает отдельные id в длинном списке — одна повторная попытка
    # специально для них, маленькими батчами, прежде чем сдаться и оставить NULL
    if missing_ids:
        logger.warning("%d упражнений не переведены с первой попытки, пробую ещё раз меньшими батчами", len(missing_ids))
        retry_items = [item for item in to_translate if item["exercise_id"] in missing_ids]
        still_missing = []

        for batch in chunked(retry_items, 10):
            translations = await translate_batch(batch)
            for item in batch:
                exercise_id = item["exercise_id"]
                translation = translations.get(exercise_id)
                if not translation or not translation.get("name_ru") or not translation.get("name_fr"):
                    still_missing.append(exercise_id)
                    continue
                await pool.execute(
                    "UPDATE exercise_library SET name_ru = $1, name_fr = $2 WHERE exercise_id = $3",
                    translation["name_ru"].strip(),
                    translation["name_fr"].strip(),
                    exercise_id,
                )
                updated_count += 1
                if len(samples) < 15:
                    samples.append((exercise_id, item["name_en"], translation["name_ru"], translation["name_fr"]))

        if still_missing:
            logger.warning(
                "%d упражнений остались без перевода даже после повтора (останутся NULL, "
                "попадут в следующий перезапуск скрипта): %s",
                len(still_missing), still_missing,
            )

    return updated_count, samples


async def main() -> None:
    try:
        updated_count, samples = await translate_all()
        print(f"\nГотово: обновлено {updated_count} записей (name_ru/name_fr)")
        print("\nПримеры переводов:")
        for exercise_id, name_en, name_ru, name_fr in samples:
            print(f"  {exercise_id:35s} | {name_en:35s} -> ru: {name_ru:35s} | fr: {name_fr}")
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
