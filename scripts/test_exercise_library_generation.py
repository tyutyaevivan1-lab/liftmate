"""
Одноразовый тестовый скрипт (НЕ часть продакшн-кода): реальные (без моков GPT/БД) прогоны
generate_workout_program/generate_split_program после рефакторинга ШАГА 3 (генерация
выбирает exercise_id из exercise_library вместо свободного текста).

Создаёт временные тестовые user_id (900000000001-900000000004) напрямую в БД, прогоняет
4 сценария, печатает результат (exercise_id/name/gif_url на упражнение), затем удаляет
тестовых пользователей.

Запуск: python scripts/test_exercise_library_generation.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio

from database import close_pool, get_pool, init_db, save_fitness_profile
import program

TEST_USER_IDS = [900000000001, 900000000002, 900000000003, 900000000004]


async def cleanup(pool) -> None:
    for user_id in TEST_USER_IDS:
        await pool.execute("DELETE FROM user_fitness_profile WHERE user_id = $1", user_id)


def print_exercises(label: str, exercises: list) -> None:
    print(f"\n--- {label} ({len(exercises)} упражнений) ---")
    for ex in exercises:
        print(f"  [{ex.get('exercise_id')}] {ex['name']}  sets={ex['sets']} reps={ex['reps']}")
        print(f"      gif_url: {ex.get('gif_url')}")


async def main() -> None:
    await init_db()
    pool = await get_pool()

    # на всякий случай убеждаемся, что тестовые id ещё не заняты реальными пользователями
    existing = await pool.fetch(
        "SELECT user_id FROM user_fitness_profile WHERE user_id = ANY($1::bigint[])", TEST_USER_IDS
    )
    if existing:
        print(f"СТОП: тестовые user_id уже существуют в БД: {[r['user_id'] for r in existing]}")
        await close_pool()
        return

    try:
        # Сценарий 1: "По цели" -> bulk (build_muscle-эквивалент), full_gym
        uid1 = TEST_USER_IDS[0]
        await save_fitness_profile(uid1, experience_months=12, equipment_type="full_gym", equipment_details=None, limitations=None)
        result1 = await program.generate_workout_program(uid1, mode="goal", language="ru", goal="bulk")
        print("\n===== СЦЕНАРИЙ 1: По цели -> bulk, full_gym =====")
        print(result1["text"])
        print_exercises("bulk/full_gym", result1["exercises"])

        # Сценарий 2: "По цели" -> cut (lose_weight-эквивалент) — проверяем исключение тяжёлых баз
        uid2 = TEST_USER_IDS[1]
        await save_fitness_profile(uid2, experience_months=6, equipment_type="full_gym", equipment_details=None, limitations=None)
        result2 = await program.generate_workout_program(uid2, mode="goal", language="ru", goal="cut")
        print("\n===== СЦЕНАРИЙ 2: По цели -> cut, full_gym (проверка исключения тяжёлых баз) =====")
        print(result2["text"])
        print_exercises("cut/full_gym", result2["exercises"])

        banned_substrings = ["жим штанги лёжа", "становая тяга", "приседания со штангой", "barbell bench press", "barbell deadlift", "barbell squat"]
        flagged = [
            ex["name"] for ex in result2["exercises"]
            if any(bad in ex["name"].lower() for bad in banned_substrings)
        ]
        if flagged:
            print(f"  !!! ВНИМАНИЕ: похоже, тяжёлые базовые движения всё же проскочили: {flagged}")
        else:
            print("  OK: тяжёлых базовых движений из чёрного списка не обнаружено")

        # Сценарий 3: "Сплит на неделю" -> upper_lower (2 дня), build_muscle, free_weights
        uid3 = TEST_USER_IDS[2]
        await save_fitness_profile(uid3, experience_months=18, equipment_type="free_weights", equipment_details=None, limitations=None, days_per_week=4)
        result3 = await program.generate_split_program(uid3, chosen_split="upper_lower", goal="build_muscle", language="ru")
        print("\n===== СЦЕНАРИЙ 3: Сплит на неделю -> upper_lower, build_muscle, free_weights =====")
        print(result3["text"])
        for i, day in enumerate(result3["days"], start=1):
            print_exercises(f"День {i}: {day['day_title']}", day["exercises"])

        # Сценарий 4: equipment_type="home" (только bodyweight) — по цели -> bulk
        uid4 = TEST_USER_IDS[3]
        await save_fitness_profile(uid4, experience_months=3, equipment_type="home", equipment_details=None, limitations=None)
        result4 = await program.generate_workout_program(uid4, mode="goal", language="ru", goal="bulk")
        print("\n===== СЦЕНАРИЙ 4: По цели -> bulk, equipment_type=home (bodyweight only) =====")
        print(result4["text"])
        print_exercises("bulk/home", result4["exercises"])

        candidates_home = await program.get_candidate_exercises(muscle_focus=None, equipment_type="home", language="ru")
        non_bodyweight = [c for c in candidates_home if c["equipment"] and any(e != "body only" and e != "bands" for e in c["equipment"])]
        print(f"\n  Проверка кандидатов для equipment_type=home: {len(candidates_home)} кандидатов, "
              f"{len(non_bodyweight)} с оборудованием вне {{body only, bands}} (ожидаем 0)")
        if non_bodyweight:
            print(f"  !!! ВНИМАНИЕ: найдены кандидаты с недопустимым оборудованием: {non_bodyweight[:5]}")

    finally:
        await cleanup(pool)
        verify = await pool.fetch(
            "SELECT user_id FROM user_fitness_profile WHERE user_id = ANY($1::bigint[])", TEST_USER_IDS
        )
        print(f"\nПосле cleanup осталось тестовых профилей: {len(verify)} (ожидаем 0)")
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
