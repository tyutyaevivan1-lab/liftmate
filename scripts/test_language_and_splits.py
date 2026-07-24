"""
Одноразовый тестовый скрипт — два независимых регрессионных прогона поверх реальной
генерации (реальный GPT, реальная БД), без моков:

ЗАДАЧА 1: подтвердить, что фикс "смешения языков" (иероглифы/латиница внутри
русского текста, см. _LANGUAGE_ENFORCEMENT_INSTRUCTIONS в program.py) держится
стабильно на большем числе прогонов (25-30, разные цели/языки), а не только на
5-10 прогонах, которыми тестировали фикс изначально.

ЗАДАЧА 2: реальная генерация для двух ранее непроверенных веток сплита —
upper_lower_x2 (проверка на повтор упражнений между базовым и вариационным днём,
тот же класс бага, что чинили для ppl_double) и bro_split (проверка, что фокус
каждого дня строго ограничен одной группой мышц, без "утечки" на смежные группы).

Использует временные тестовые user_id (900000000301-900000000305), удаляет их
после прогона.

Запуск: ./venv/bin/python scripts/test_language_and_splits.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
import re

from database import close_pool, get_pool, init_db, save_fitness_profile
import program

TEST_USER_IDS = {
    "ru": 900000000301,
    "en": 900000000302,
    "fr": 900000000303,
    "upper_lower_x2": 900000000304,
    "bro_split": 900000000305,
}

RUNS_PER_LANGUAGE = 10

_CJK_RE = re.compile(r"[一-鿿぀-ヿ가-힯]")
_CYRILLIC_RE = re.compile(r"[Ѐ-ӿ]")
_LATIN_RE = re.compile(r"[a-zA-Z]")


def find_script_contamination(text: str, language: str) -> list:
    """
    Возвращает список найденных проблем в тексте для заданного языка интерфейса:
    - любой символ CJK (китайский/японский/корейский) — всегда ошибка для ru/en/fr;
    - смешение кириллицы и латиницы ВНУТРИ ОДНОГО СЛОВА — ошибка для ru (кроме
      отдельных слов целиком латиницей, которые могут быть общепринятыми
      аббревиатурами оборудования, например "TRX" — это НЕ внутри слова).
    """
    problems = []
    if _CJK_RE.search(text):
        problems.append(f"CJK-символы в тексте: {text!r}")

    if language == "ru":
        for word in re.findall(r"\S+", text):
            has_cyr = bool(_CYRILLIC_RE.search(word))
            has_lat = bool(_LATIN_RE.search(word))
            if has_cyr and has_lat:
                problems.append(f"смешение кириллицы и латиницы внутри слова: {word!r} (полный текст: {text!r})")

    return problems


async def cleanup(pool) -> None:
    for user_id in TEST_USER_IDS.values():
        await pool.execute("DELETE FROM user_fitness_profile WHERE user_id = $1", user_id)


async def task1_language_check(pool) -> list:
    print("=" * 70)
    print("ЗАДАЧА 1: проверка смешения языков/иероглифов на", RUNS_PER_LANGUAGE * 3, "прогонах")
    print("=" * 70)

    for lang, uid in [("ru", TEST_USER_IDS["ru"]), ("en", TEST_USER_IDS["en"]), ("fr", TEST_USER_IDS["fr"])]:
        await save_fitness_profile(uid, experience_months=12, equipment_type="full_gym", equipment_details=None, limitations=None)

    all_problems = []
    run_count = 0

    for lang, uid in [("ru", TEST_USER_IDS["ru"]), ("en", TEST_USER_IDS["en"]), ("fr", TEST_USER_IDS["fr"])]:
        for i in range(RUNS_PER_LANGUAGE):
            goal = program.GOALS[i % len(program.GOALS)]
            result = await program.generate_workout_program(uid, mode="goal", language=lang, goal=goal)
            run_count += 1

            texts_to_check = [("text", result["text"])]
            for ex in result["exercises"]:
                texts_to_check.append((f"exercise[{ex.get('exercise_id')}].name", ex["name"]))
                texts_to_check.append((f"exercise[{ex.get('exercise_id')}].why", ex["why"]))

            for field, text in texts_to_check:
                problems = find_script_contamination(text, lang)
                for problem in problems:
                    all_problems.append((lang, goal, i + 1, field, problem))

            print(f"  [{lang}] прогон {i + 1}/{RUNS_PER_LANGUAGE} (goal={goal}): {len(result['exercises'])} упражнений, OK" if not any(
                find_script_contamination(t, lang) for _, t in texts_to_check
            ) else f"  [{lang}] прогон {i + 1}/{RUNS_PER_LANGUAGE} (goal={goal}): НАЙДЕНА ПРОБЛЕМА")

    print(f"\nВсего прогонов: {run_count}")
    if all_problems:
        print(f"НАЙДЕНО ПРОБЛЕМ: {len(all_problems)}")
        for lang, goal, run_idx, field, problem in all_problems:
            print(f"  [{lang}, goal={goal}, run={run_idx}] {field}: {problem}")
    else:
        print("Проблем не найдено ни разу — фикс держится стабильно.")

    return all_problems


BRO_SPLIT_EXPECTED_BODY_PARTS = {
    "Chest only": {"chest"},
    "Back only": {"back"},
    "Shoulders only": {"shoulders"},
    "Arms — biceps and triceps": {"biceps", "triceps"},
    "Legs — quads, hamstrings, glutes, calves": {"legs"},
}


async def check_body_part_purity(pool, days: list, focus_labels: list) -> list:
    """Сверяет реальный body_part каждого выбранного упражнения (из БД) с ожидаемым для дня."""
    violations = []
    for day, focus_label in zip(days, focus_labels):
        expected = BRO_SPLIT_EXPECTED_BODY_PARTS.get(focus_label)
        if expected is None:
            continue
        exercise_ids = [ex["exercise_id"] for ex in day["exercises"]]
        rows = await pool.fetch(
            "SELECT exercise_id, name_en, body_part FROM exercise_library WHERE exercise_id = ANY($1::text[])",
            exercise_ids,
        )
        for row in rows:
            if row["body_part"] not in expected:
                violations.append((focus_label, row["exercise_id"], row["name_en"], row["body_part"], expected))
    return violations


async def task2_split_check(pool) -> None:
    print("\n" + "=" * 70)
    print("ЗАДАЧА 2: непроверенные ветки сплита — upper_lower_x2, bro_split")
    print("=" * 70)

    # upper_lower_x2: 4 дня/нед, build_muscle
    uid_ulx2 = TEST_USER_IDS["upper_lower_x2"]
    await save_fitness_profile(
        uid_ulx2, experience_months=18, equipment_type="full_gym", equipment_details=None,
        limitations=None, days_per_week=4, chosen_split="upper_lower_x2",
    )
    result_ulx2 = await program.generate_split_program(uid_ulx2, "upper_lower_x2", "build_muscle", "ru")

    print("\n----- upper_lower_x2 (build_muscle, full_gym) -----")
    for i, day in enumerate(result_ulx2["days"]):
        print(f"\nДень {i + 1}: {day['day_title']}")
        for ex in day["exercises"]:
            print(f"  [{ex.get('exercise_id')}] {ex['name']} — {ex['sets']}x{ex['reps']}")

    # Проверка на повтор между базовым (день 1: Upper) и вариационным (день 3: Upper variation)
    # и между днём 2 (Lower) и днём 4 (Lower variation)
    day1_ids = {ex["exercise_id"] for ex in result_ulx2["days"][0]["exercises"]}
    day3_ids = {ex["exercise_id"] for ex in result_ulx2["days"][2]["exercises"]}
    day2_ids = {ex["exercise_id"] for ex in result_ulx2["days"][1]["exercises"]}
    day4_ids = {ex["exercise_id"] for ex in result_ulx2["days"][3]["exercises"]}

    upper_overlap = day1_ids & day3_ids
    lower_overlap = day2_ids & day4_ids
    print(f"\nПовтор упражнений Upper (день 1) <-> Upper variation (день 3): {upper_overlap or 'нет повторов'}")
    print(f"Повтор упражнений Lower (день 2) <-> Lower variation (день 4): {lower_overlap or 'нет повторов'}")

    # bro_split: 5-6 дней/нед, опытный пользователь (36+ месяцев), strength
    uid_bro = TEST_USER_IDS["bro_split"]
    await save_fitness_profile(
        uid_bro, experience_months=40, equipment_type="full_gym", equipment_details=None,
        limitations=None, days_per_week=5, chosen_split="bro_split",
    )
    result_bro = await program.generate_split_program(uid_bro, "bro_split", "strength", "ru")

    print("\n----- bro_split (strength, 40 месяцев стажа, full_gym) -----")
    for i, day in enumerate(result_bro["days"]):
        print(f"\nДень {i + 1}: {day['day_title']}")
        for ex in day["exercises"]:
            print(f"  [{ex.get('exercise_id')}] {ex['name']} — {ex['sets']}x{ex['reps']} — {ex['why']}")

    focus_labels = program.SPLIT_DAY_FOCUS["bro_split"]
    violations = await check_body_part_purity(pool, result_bro["days"], focus_labels)
    print("\nПроверка утечки упражнений на смежные группы мышц (по реальному body_part из БД):")
    if violations:
        for focus_label, exercise_id, name, actual_body_part, expected in violations:
            print(f"  !!! УТЕЧКА: день {focus_label!r} содержит [{exercise_id}] {name} с body_part={actual_body_part!r}, ожидалось одно из {expected}")
    else:
        print("  OK: утечек не найдено — все упражнения строго в пределах ожидаемой группы мышц")

    return result_ulx2, result_bro, upper_overlap, lower_overlap, violations


async def main() -> None:
    await init_db()
    pool = await get_pool()

    existing = await pool.fetch(
        "SELECT user_id FROM user_fitness_profile WHERE user_id = ANY($1::bigint[])",
        list(TEST_USER_IDS.values()),
    )
    if existing:
        print(f"СТОП: тестовые user_id уже существуют в БД: {[r['user_id'] for r in existing]}")
        await close_pool()
        return

    try:
        language_problems = await task1_language_check(pool)
        _, _, upper_overlap, lower_overlap, violations = await task2_split_check(pool)

        print("\n" + "=" * 70)
        print("ИТОГ")
        print("=" * 70)
        print(f"Задача 1 (языки): {'ПРОБЛЕМЫ НАЙДЕНЫ' if language_problems else 'OK, проблем не найдено'}")
        print(f"Задача 2 (upper_lower_x2 повторы): {'ПОВТОРЫ ЕСТЬ' if (upper_overlap or lower_overlap) else 'OK, повторов нет'}")
        print(f"Задача 2 (bro_split утечки групп мышц): {'УТЕЧКИ ЕСТЬ' if violations else 'OK, утечек нет'}")
    finally:
        await cleanup(pool)
        verify = await pool.fetch(
            "SELECT user_id FROM user_fitness_profile WHERE user_id = ANY($1::bigint[])",
            list(TEST_USER_IDS.values()),
        )
        print(f"\nПосле cleanup осталось тестовых профилей: {len(verify)} (ожидаем 0)")
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
