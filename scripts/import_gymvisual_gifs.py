"""
Одноразовый скрипт: заменяет статичные фото free-exercise-db в exercise_library на
реальные анимированные гифки из hasaneyldrm/exercises-dataset (https://github.com/
hasaneyldrm/exercises-dataset), там, где для упражнения нашлось надёжное соответствие.

ВАЖНО про лицензию медиа: гифки/картинки этого датасета — © Gym visual
(https://gymvisual.com/), НЕ MIT (MIT в датасете покрывает только код/данные/переводы,
см. LICENSE и NOTICE.md репозитория). Использование в LiftMate согласовано отдельно,
напрямую с владельцем датасета (у которого есть лицензия от Gym visual) — НЕ через сам
факт публикации репозитория на GitHub (LICENSE прямо пишет: "cloning this repository
does not grant you any license to the media"). NOTICE.md требует сохранять атрибуцию
"© Gym visual — https://gymvisual.com/" при любом использовании — она пишется в новую
колонку exercise_library.media_attribution и выводится на Telegraph-странице рядом с
картинкой (см. program._build_program_html).

Разрешение (180x180) проверено вручную (см. обсуждение с пользователем) — соответствует
тому, что заявлено в NOTICE.md ("distributed at 180×180 only"), поэтому скрипт просто
берёт media_id/gif_url/image как есть, без ресайза.

Сопоставление упражнений между датасетами — ПО НАЗВАНИЮ (у датасетов совершенно разные
схемы id), а не по exercise_id. Точное совпадение нормализованной строки не работает
хорошо (разный порядок слов, например "Bent Over Barbell Row" в нашей таблице против
"barbell bent over row" в новом датасете) — поэтому матчинг по МНОЖЕСТВУ слов (token set,
без учёта порядка и регистра). Совпадение считается надёжным, только если у нормализованного
множества слов ОДНО-единственное соответствие в новом датасете (без неоднозначности) —
это осознанно консервативно: часть упражнений (~78% в первом прогоне) останется без
замены и продолжит использовать старое статичное фото free-exercise-db как fallback —
это ожидаемо и разрешено планом ("не удаляй записи, для которых нет соответствия").

Запуск: ./venv/bin/python scripts/import_gymvisual_gifs.py
"""

import json
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio

from database import close_pool, get_pool, init_db

EXERCISES_JSON_URL = "https://raw.githubusercontent.com/hasaneyldrm/exercises-dataset/main/data/exercises.json"
MEDIA_BASE = "https://raw.githubusercontent.com/hasaneyldrm/exercises-dataset/main/"

GYM_VISUAL_ATTRIBUTION = "© Gym visual — https://gymvisual.com/"


def tokenset(name: str) -> frozenset:
    name = name.lower()
    name = re.sub(r"[^a-z0-9]+", " ", name)
    return frozenset(name.split())


def fetch_new_dataset() -> list:
    print(f"Скачиваю {EXERCISES_JSON_URL} ...")
    with urllib.request.urlopen(EXERCISES_JSON_URL, timeout=30) as response:
        data = json.loads(response.read())
    print(f"Скачано {len(data)} упражнений из hasaneyldrm/exercises-dataset")
    return data


def build_unambiguous_lookup(new_data: list) -> dict:
    """tokenset(name) -> item, только для множеств слов с ОДНИМ совпадением в новом датасете."""
    by_tokens: dict = {}
    for item in new_data:
        ts = tokenset(item["name"])
        by_tokens.setdefault(ts, []).append(item)

    return {ts: items[0] for ts, items in by_tokens.items() if len(items) == 1}


async def import_gifs() -> tuple:
    await init_db()
    pool = await get_pool()

    new_data = fetch_new_dataset()
    lookup = build_unambiguous_lookup(new_data)

    rows = await pool.fetch("SELECT exercise_id, name_en FROM exercise_library")
    print(f"В exercise_library {len(rows)} записей, проверяю соответствия...")

    updated = 0
    samples = []
    for row in rows:
        ts = tokenset(row["name_en"])
        match = lookup.get(ts)
        if match is None:
            continue

        new_gif_url = MEDIA_BASE + match["gif_url"]
        await pool.execute(
            """
            UPDATE exercise_library
            SET gif_url = $1, media_attribution = $2
            WHERE exercise_id = $3
            """,
            new_gif_url,
            GYM_VISUAL_ATTRIBUTION,
            row["exercise_id"],
        )
        updated += 1
        if len(samples) < 15:
            samples.append((row["exercise_id"], row["name_en"], match["name"], new_gif_url))

    return updated, len(rows), samples


async def main() -> None:
    try:
        updated, total, samples = await import_gifs()
        print(f"\nГотово: заменено {updated} из {total} записей на реальные гифки Gym visual")
        print(f"Оставлено без изменений (fallback на статичное фото free-exercise-db): {total - updated}")
        print("\nПримеры замен:")
        for exercise_id, our_name, their_name, gif_url in samples:
            print(f"  {exercise_id:40s} | {our_name:40s} -> matched: {their_name:40s} | {gif_url}")
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
