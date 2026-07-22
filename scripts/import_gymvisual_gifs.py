"""
Одноразовый скрипт: заменяет статичные фото free-exercise-db в exercise_library на
реальные анимированные гифки из hasaneyldrm/exercises-dataset (https://github.com/
hasaneyldrm/exercises-dataset), и деактивирует упражнения, для которых в новом
датасете вообще нет соответствия — чтобы в Telegraph-публикациях был ЕДИНЫЙ стиль
(только анимации Gym visual), а не смесь гифок и старых статичных фото (см. явное
решение пользователя после обсуждения фактического покрытия матчинга).

ВАЖНО про лицензию медиа: гифки/картинки этого датасета — © Gym visual
(https://gymvisual.com/), НЕ MIT (MIT в датасете покрывает только код/данные/переводы,
см. LICENSE и NOTICE.md репозитория). Использование в LiftMate согласовано отдельно,
напрямую с владельцем датасета (у которого есть лицензия от Gym visual) — НЕ через сам
факт публикации репозитория на GitHub (LICENSE прямо пишет: "cloning this repository
does not grant you any license to the media"). NOTICE.md требует сохранять атрибуцию
"© Gym visual — https://gymvisual.com/" при любом использовании — она пишется в
колонку exercise_library.media_attribution и выводится на Telegraph-странице рядом с
картинкой (см. program._build_program_html).

Разрешение (180x180) проверено вручную (см. обсуждение с пользователем) — соответствует
тому, что заявлено в NOTICE.md ("distributed at 180×180 only"), поэтому скрипт просто
берёт media_id/gif_url/image как есть, без ресайза.

Сопоставление упражнений между датасетами — ПО НАЗВАНИЮ (у датасетов совершенно разные
схемы id), а не по exercise_id, в ДВА прохода, от самого строгого к менее строгому:

1. Точное совпадение множества слов (token set, без учёта порядка/регистра) — надёжно,
   только если множество слов ОДНО-единственное во всём новом датасете (без
   неоднозначности).
2. Совпадение "подмножество": слова одного названия являются подмножеством слов
   другого (например одно название — более общая/короткая версия другого — "Leg
   Press" vs "Smith Leg Press"), с симметрической разницей ≤ 2 слов и ТОЖЕ только
   если лучший кандидат единственный. Ловит случаи вида "лишнее слово с одной
   стороны" (уточнение оборудования/техники), но не пытается угадывать более
   отдалённые совпадения — это осознанный компромисс между покрытием и риском
   показать гифку от другого упражнения.

Упражнения, для которых НИ ОДИН из проходов не дал совпадения (в первом прогоне —
513 из 873), — это упражнения, которых просто нет в новом датасете (он не является
надмножеством нашего). Для них ставится is_active = false: они перестают попадать в
кандидатов для GPT (см. program.get_candidate_exercises, WHERE is_active = true) и,
как следствие, никогда не появляются в сгенерированных программах — вместо того чтобы
показывать их со старым фото free-exercise-db и ломать единый стиль.

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

# Максимальная симметрическая разница множеств слов для прохода 2 (подмножество слов)
MAX_SUBSET_DIFF = 2


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


def build_exact_lookup(new_data: list) -> dict:
    """tokenset(name) -> item, только для множеств слов с ОДНИМ совпадением в новом датасете."""
    by_tokens: dict = {}
    for item in new_data:
        ts = tokenset(item["name"])
        by_tokens.setdefault(ts, []).append(item)

    return {ts: items[0] for ts, items in by_tokens.items() if len(items) == 1}


def find_subset_match(our_ts: frozenset, new_tokensets: list):
    """
    Ищет среди new_tokensets (список (tokenset, item)) кандидатов, чьё множество слов
    является надмножеством/подмножеством our_ts, выбирает единственного с наименьшей
    симметрической разницей (≤ MAX_SUBSET_DIFF). Возвращает item или None, если нет
    надёжного единственного кандидата.
    """
    candidates = []
    for their_ts, item in new_tokensets:
        if our_ts <= their_ts or their_ts <= our_ts:
            diff = len(our_ts.symmetric_difference(their_ts))
            if diff <= MAX_SUBSET_DIFF:
                candidates.append((diff, item))

    if not candidates:
        return None

    candidates.sort(key=lambda pair: pair[0])
    best_diff = candidates[0][0]
    best_items = [item for diff, item in candidates if diff == best_diff]
    return best_items[0] if len(best_items) == 1 else None


async def import_gifs() -> dict:
    await init_db()
    pool = await get_pool()

    new_data = fetch_new_dataset()
    exact_lookup = build_exact_lookup(new_data)
    new_tokensets = [(tokenset(item["name"]), item) for item in new_data]

    rows = await pool.fetch("SELECT exercise_id, name_en FROM exercise_library")
    print(f"В exercise_library {len(rows)} записей, проверяю соответствия...")

    exact_matches = 0
    subset_matches = 0
    deactivated = 0
    samples_exact = []
    samples_subset = []
    deactivated_names = []

    for row in rows:
        ts = tokenset(row["name_en"])

        match = exact_lookup.get(ts)
        matched_via = "exact"
        if match is None:
            match = find_subset_match(ts, new_tokensets)
            matched_via = "subset"

        if match is not None:
            new_gif_url = MEDIA_BASE + match["gif_url"]
            await pool.execute(
                """
                UPDATE exercise_library
                SET gif_url = $1, media_attribution = $2, is_active = true
                WHERE exercise_id = $3
                """,
                new_gif_url,
                GYM_VISUAL_ATTRIBUTION,
                row["exercise_id"],
            )
            if matched_via == "exact":
                exact_matches += 1
                if len(samples_exact) < 10:
                    samples_exact.append((row["exercise_id"], row["name_en"], match["name"], new_gif_url))
            else:
                subset_matches += 1
                if len(samples_subset) < 10:
                    samples_subset.append((row["exercise_id"], row["name_en"], match["name"], new_gif_url))
            continue

        # Нет надёжного соответствия в новом датасете вообще — деактивируем, чтобы не
        # ломать единый стиль старым статичным фото free-exercise-db (см. docstring).
        await pool.execute("UPDATE exercise_library SET is_active = false WHERE exercise_id = $1", row["exercise_id"])
        deactivated += 1
        deactivated_names.append(row["name_en"])

    return {
        "total": len(rows),
        "exact_matches": exact_matches,
        "subset_matches": subset_matches,
        "deactivated": deactivated,
        "samples_exact": samples_exact,
        "samples_subset": samples_subset,
        "deactivated_names": deactivated_names,
    }


async def main() -> None:
    try:
        result = await import_gifs()
        total_matched = result["exact_matches"] + result["subset_matches"]
        print(f"\nГотово. Всего записей: {result['total']}")
        print(f"  Точное совпадение множества слов: {result['exact_matches']}")
        print(f"  Совпадение по подмножеству слов (diff <= {MAX_SUBSET_DIFF}): {result['subset_matches']}")
        print(f"  Итого с реальной гифкой Gym visual: {total_matched}")
        print(f"  Деактивировано (is_active=false, нет соответствия в датасете): {result['deactivated']}")

        print("\nПримеры точных совпадений:")
        for exercise_id, our_name, their_name, gif_url in result["samples_exact"]:
            print(f"  {exercise_id:40s} | {our_name:40s} -> {their_name}")

        print("\nПримеры совпадений по подмножеству:")
        for exercise_id, our_name, their_name, gif_url in result["samples_subset"]:
            print(f"  {exercise_id:40s} | {our_name:40s} -> {their_name}")

        print(f"\nПримеры деактивированных ({min(15, len(result['deactivated_names']))} из {len(result['deactivated_names'])}):")
        for name in result["deactivated_names"][:15]:
            print(f"  {name}")
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
