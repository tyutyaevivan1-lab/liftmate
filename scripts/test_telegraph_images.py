"""
Одноразовый тестовый скрипт: финальный шаг плана иллюстраций упражнений — проверяет,
что _build_program_html() теперь вставляет <img src="gif_url"> для каждого упражнения
(см. program.py:_build_program_html) и реально публикует страницы в Telegraph.

Прогоняет несколько реальных (без моков) сценариев через generate_workout_program/
generate_split_program + publish_program (в реальный Telegraph-аккаунт бота), плюс
отдельно — сценарий с fallback-упражнениями без gif_url (программа с exercise_id=None),
чтобы убедиться, что отсутствие картинки не ломает сборку страницы.

Использует временные тестовые user_id (900000000101-900000000103), удаляет их после
прогона.

Запуск: ./venv/bin/python scripts/test_telegraph_images.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
import re

from database import close_pool, get_pool, init_db, save_fitness_profile
import program

TEST_USER_IDS = [900000000101, 900000000102, 900000000103]


async def cleanup(pool) -> None:
    for user_id in TEST_USER_IDS:
        await pool.execute("DELETE FROM user_fitness_profile WHERE user_id = $1", user_id)


def count_images(html_content: str) -> int:
    return len(re.findall(r"<img\b", html_content))


async def main() -> None:
    await init_db()
    pool = await get_pool()

    existing = await pool.fetch(
        "SELECT user_id FROM user_fitness_profile WHERE user_id = ANY($1::bigint[])", TEST_USER_IDS
    )
    if existing:
        print(f"СТОП: тестовые user_id уже существуют в БД: {[r['user_id'] for r in existing]}")
        await close_pool()
        return

    try:
        # Сценарий 1: "По цели" -> bulk, full_gym (обычная генерация, ожидаем картинки у всех упражнений)
        uid1 = TEST_USER_IDS[0]
        await save_fitness_profile(uid1, experience_months=12, equipment_type="full_gym", equipment_details=None, limitations=None)
        result1 = await program.generate_workout_program(uid1, mode="goal", language="ru", goal="bulk")
        days1 = [{"day_title": None, "exercises": result1["exercises"]}]
        html1 = program._build_program_html(days1, "ru")
        print("\n===== СЦЕНАРИЙ 1: По цели -> bulk, full_gym =====")
        print(f"Упражнений: {len(result1['exercises'])}, <img> тегов в HTML: {count_images(html1)}")
        url1 = await program._create_program_page(days1, "ru", "Тест Bulk")
        print(f"Telegraph URL: {url1}")

        # Сценарий 2: "Сплит на неделю" -> ppl_single (3 дня), lose_weight, free_weights
        uid2 = TEST_USER_IDS[1]
        await save_fitness_profile(uid2, experience_months=18, equipment_type="free_weights", equipment_details=None, limitations=None, days_per_week=4)
        result2 = await program.generate_split_program(uid2, chosen_split="ppl_single", goal="lose_weight", language="ru")
        html2 = program._build_program_html(result2["days"], "ru")
        total_ex2 = sum(len(day["exercises"]) for day in result2["days"])
        print("\n===== СЦЕНАРИЙ 2: Сплит на неделю -> ppl_single, lose_weight, free_weights =====")
        print(f"Дней: {len(result2['days'])}, всего упражнений: {total_ex2}, <img> тегов в HTML: {count_images(html2)}")
        url2 = await program._create_program_page(result2["days"], "ru", "Тест PPL")
        print(f"Telegraph URL: {url2}")

        # Сценарий 3: "По цели" -> endurance, home (bodyweight)
        uid3 = TEST_USER_IDS[2]
        await save_fitness_profile(uid3, experience_months=3, equipment_type="home", equipment_details=None, limitations=None)
        result3 = await program.generate_workout_program(uid3, mode="goal", language="ru", goal="endurance")
        days3 = [{"day_title": None, "exercises": result3["exercises"]}]
        html3 = program._build_program_html(days3, "ru")
        print("\n===== СЦЕНАРИЙ 3: По цели -> endurance, home (bodyweight) =====")
        print(f"Упражнений: {len(result3['exercises'])}, <img> тегов в HTML: {count_images(html3)}")
        url3 = await program._create_program_page(days3, "ru", "Тест Endurance")
        print(f"Telegraph URL: {url3}")

        # Сценарий 4: fallback-упражнения БЕЗ gif_url (exercise_id=None) — искусственно берём
        # статичный шаблон напрямую, минуя GPT, чтобы гарантированно получить отсутствие картинок
        print("\n===== СЦЕНАРИЙ 4: fallback-программа без gif_url (статичный шаблон) =====")
        fallback = program._fallback_program("ru")
        days4 = [{"day_title": None, "exercises": fallback["exercises"]}]
        html4 = program._build_program_html(days4, "ru")
        print(f"Упражнений: {len(fallback['exercises'])}, <img> тегов в HTML: {count_images(html4)} (ожидаем 0)")
        url4 = await program._create_program_page(days4, "ru", "Тест Fallback")
        print(f"Telegraph URL: {url4}")

        # Собираем все gif_url из сценариев 1-3 и проверяем, что картинки реально отдаются (HTTP 200)
        print("\n===== Проверка HTTP-статуса картинок =====")
        all_gif_urls = [ex["gif_url"] for ex in result1["exercises"] if ex.get("gif_url")]
        all_gif_urls += [ex["gif_url"] for day in result2["days"] for ex in day["exercises"] if ex.get("gif_url")]
        all_gif_urls += [ex["gif_url"] for ex in result3["exercises"] if ex.get("gif_url")]

        import httpx
        async with httpx.AsyncClient() as client:
            for url in all_gif_urls:
                try:
                    resp = await client.head(url, timeout=10, follow_redirects=True)
                    status = resp.status_code
                except Exception as exc:
                    status = f"ERROR: {exc}"
                print(f"  {status}  {url}")

    finally:
        await cleanup(pool)
        verify = await pool.fetch(
            "SELECT user_id FROM user_fitness_profile WHERE user_id = ANY($1::bigint[])", TEST_USER_IDS
        )
        print(f"\nПосле cleanup осталось тестовых профилей: {len(verify)} (ожидаем 0)")
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
