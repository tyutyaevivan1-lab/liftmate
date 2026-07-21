"""
Одноразовый скрипт: импортирует базу упражнений free-exercise-db (Unlicense, public
domain — https://github.com/yuhonas/free-exercise-db) в таблицу exercise_library.

Это ШАГ 1 плана добавления иллюстраций техники упражнений. Специально НЕ используется
датасет ExerciseDB/exercisedb-api — тот репозиторий снят с GitHub по DMCA как
неавторизованная копия коммерческого датасета (см. обсуждение в задаче), поэтому вместо
него взят genuinely открытый free-exercise-db.

Что делает скрипт:
1. Скачивает объединённый exercises.json напрямую с raw.githubusercontent.com (~1 МБ,
   873 упражнения на момент написания) — сам датасет нигде в репозитории не хранится.
2. Для каждого упражнения превращает относительный путь картинки в полный URL (картинки
   тоже остаются на GitHub — см. FREE_EXERCISE_DB_MEDIA_BASE, копировать файлы себе на
   этом шаге не нужно).
3. Апсертит в exercise_library по exercise_id (PRIMARY KEY) — скрипт безопасно перезапускать.

ВАЖНО: free-exercise-db хранит СТАТИЧНЫЕ JPG-фотографии техники (обычно 2 на упражнение:
начало/конец движения), а НЕ анимированные гифки. Первая картинка кладётся в колонку
gif_url (имя колонки зафиксировано схемой из брифа) — реальные гифки/видео это отдельный
будущий шаг плана (либо купить официальный ExerciseDB API, либо найти/сделать другой
источник — см. обсуждение с пользователем).

name_ru/name_fr намеренно оставляются NULL — перевод названий это следующий шаг.

Запуск: python scripts/import_exercise_library.py
"""

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio

from database import close_pool, get_pool, init_db

EXERCISES_JSON_URL = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/dist/exercises.json"
# Сами картинки в репозитории лежат в exercises/<путь из "images">, отдельно от
# объединённого dist/exercises.json — поэтому базовый URL для картинок другой
FREE_EXERCISE_DB_MEDIA_BASE = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/exercises/"

# Грубая группировка конкретных мышц (primaryMuscles[0] из датасета) в область тела —
# такого поля в free-exercise-db нет напрямую, а body_part в нашей схеме подразумевает
# именно широкую группу (как категории в exercises_data.py: грудь/спина/ноги/...).
MUSCLE_TO_BODY_PART = {
    "chest": "chest",
    "lats": "back",
    "middle back": "back",
    "lower back": "back",
    "traps": "back",
    "quadriceps": "legs",
    "hamstrings": "legs",
    "glutes": "legs",
    "calves": "legs",
    "abductors": "legs",
    "adductors": "legs",
    "shoulders": "shoulders",
    "biceps": "biceps",
    "triceps": "triceps",
    "forearms": "forearms",
    "abdominals": "core",
    "neck": "neck",
}


def fetch_exercises() -> list:
    """Скачивает объединённый датасет напрямую с GitHub — нигде локально не кешируется."""
    print(f"Скачиваю {EXERCISES_JSON_URL} ...")
    with urllib.request.urlopen(EXERCISES_JSON_URL, timeout=30) as response:
        data = json.loads(response.read())
    print(f"Скачано {len(data)} упражнений")
    return data


def to_row(exercise: dict) -> dict:
    """Преобразует одну запись free-exercise-db в строку под схему exercise_library."""
    primary_muscles = exercise.get("primaryMuscles") or []
    target_muscle = primary_muscles[0] if primary_muscles else None
    body_part = MUSCLE_TO_BODY_PART.get(target_muscle) if target_muscle else None

    equipment = exercise.get("equipment")
    equipment_list = [equipment] if equipment else []

    images = exercise.get("images") or []
    gif_url = f"{FREE_EXERCISE_DB_MEDIA_BASE}{images[0]}" if images else None

    return {
        "exercise_id": exercise["id"],
        "name_en": exercise["name"],
        "body_part": body_part,
        "target_muscle": target_muscle,
        "secondary_muscles": exercise.get("secondaryMuscles") or [],
        "equipment": equipment_list,
        "gif_url": gif_url,
        "instructions": exercise.get("instructions") or [],
    }


async def import_exercises() -> int:
    await init_db()  # на случай, если exercise_library ещё не создана на этой базе
    pool = await get_pool()

    exercises = fetch_exercises()
    rows = [to_row(exercise) for exercise in exercises]

    inserted = 0
    for row in rows:
        await pool.execute(
            """
            INSERT INTO exercise_library
                (exercise_id, name_en, body_part, target_muscle, secondary_muscles,
                 equipment, gif_url, instructions, is_active)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, true)
            ON CONFLICT (exercise_id) DO UPDATE SET
                name_en = excluded.name_en,
                body_part = excluded.body_part,
                target_muscle = excluded.target_muscle,
                secondary_muscles = excluded.secondary_muscles,
                equipment = excluded.equipment,
                gif_url = excluded.gif_url,
                instructions = excluded.instructions
            """,
            # name_ru/name_fr/video_url/is_active сознательно НЕ включены в UPDATE SET —
            # чтобы повторный запуск скрипта (например, после обновления датасета) не
            # затирал перевод названий или видео, добавленные последующими шагами плана
            row["exercise_id"],
            row["name_en"],
            row["body_part"],
            row["target_muscle"],
            row["secondary_muscles"],
            row["equipment"],
            row["gif_url"],
            row["instructions"],
        )
        inserted += 1

    return inserted


async def main() -> None:
    try:
        count = await import_exercises()
        print(f"\nГотово: импортировано/обновлено {count} упражнений в exercise_library")
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
