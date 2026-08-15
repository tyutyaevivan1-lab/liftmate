"""
Одноразовый тестовый скрипт: система "целевого" streak + звания (см. streak_goals.py,
database.py: user_streak_goals/get_workout_dates, api.py: GET /api/user/{user_id}/streak).

Часть 1 — чистые проверки streak_goals.compute_streak/get_rank_title (без БД, детерминированно).

Часть 2 — реальный сквозной прогон: временный тестовый user_id, расписание пн/ср/пт,
НАСТОЯЩИЕ строки в таблице workouts (вставляются напрямую, т.к. add_workout не позволяет
задать произвольную дату) за 3 полные недели без пропусков -> проверяем, что streak растёт
до 9. Затем добавляем ещё один успешный день (10) и намеренно ПРОПУСКАЕМ следующий
запланированный день -> проверяем, что streak сбрасывается на 0, а longest_streak
сохраняет исторический максимум (10). Вызывается напрямую функция эндпоинта api.get_streak
(минуя HTTP-слой — тот же приём, что и в прошлых тестах api.py в этом проекте), с реальной
БД и реальным подсчётом.

Использует временный тестовый user_id (900000000601), удаляет все его данные после теста.

Запуск: ./venv/bin/python scripts/test_streak_goals.py
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio

import api
import streak_goals
from database import close_pool, get_pool, init_db

TEST_USER_ID = 900000000601


def test_pure_compute_streak() -> list:
    print("=" * 70)
    print("ЧАСТЬ 1: streak_goals.compute_streak / get_rank_title (без БД)")
    print("=" * 70)
    failures = []

    target = {1, 3, 5}  # пн/ср/пт
    schedule_set_at = date(2026, 1, 5)  # понедельник

    # Идеальное посещение 3 недель подряд (9 дней), today = день сразу после последнего
    perfect_dates = set(streak_goals._scheduled_dates_between(target, schedule_set_at, date(2026, 1, 23)))
    result = streak_goals.compute_streak(target, perfect_dates, schedule_set_at, date(2026, 1, 24))
    print(f"Идеальные 3 недели: current={result['current_streak']} longest={result['longest_streak']}")
    if result["current_streak"] != 9 or result["longest_streak"] != 9:
        failures.append(f"Ожидалось current=9 longest=9, получено {result}")

    # Пропущена среда второй недели (2026-01-14) -> streak должен прерваться на этом дне
    with_gap = perfect_dates - {date(2026, 1, 14)}
    result_gap = streak_goals.compute_streak(target, with_gap, schedule_set_at, date(2026, 1, 24))
    print(f"С пропуском одной ср: current={result_gap['current_streak']} longest={result_gap['longest_streak']}")
    # После пропуска 14-го числа остаются ещё пт(16), пн(19), ср(21), пт(23) -> 4 подряд
    if result_gap["current_streak"] != 4:
        failures.append(f"Ожидалось current=4 после пропуска, получено {result_gap['current_streak']}")
    if result_gap["longest_streak"] != 4:
        # до пропуска было всего 2 дня (пн+ср 5,7 января), после — 4 дня, максимум = 4
        failures.append(f"Ожидалось longest=4, получено {result_gap['longest_streak']}")

    # Сегодняшний целевой день ещё не наступил (нет тренировки) -> НЕ должен считаться пропуском
    today_pending = streak_goals.compute_streak(target, set(), date(2026, 1, 5), date(2026, 1, 5))
    print(f"Сегодня целевой день, тренировки ещё нет: current={today_pending['current_streak']} (ожидаем 0, не минус)")
    if today_pending["current_streak"] != 0:
        failures.append(f"Ожидалось current=0 (не сломан, просто ещё не начат), получено {today_pending}")

    # Рост streak неделя за неделей (варьируем "today", имитируя течение времени) —
    # без пропусков, каждую неделю добавляем очередные пн/ср/пт
    print("\nРост streak по неделям (только пн/ср/пт, без пропусков):")
    all_perfect = set()
    for week_end, label in [(date(2026, 1, 9), "неделя 1"), (date(2026, 1, 16), "неделя 2"), (date(2026, 1, 23), "неделя 3")]:
        all_perfect |= set(streak_goals._scheduled_dates_between(target, schedule_set_at, week_end))
        weekly = streak_goals.compute_streak(target, all_perfect, schedule_set_at, week_end + timedelta(days=1))
        print(f"  после {label}: current={weekly['current_streak']} longest={weekly['longest_streak']}")
    if weekly["current_streak"] != 9:
        failures.append(f"Ожидалось current=9 после 3 недель роста, получено {weekly['current_streak']}")

    print("\nЗвания по общему числу тренировок:")
    for n in [0, 1, 2, 3, 6, 7, 14, 15, 29, 30, 45]:
        titles = {lang: streak_goals.get_rank_title(n, lang) for lang in ("ru", "en", "fr")}
        print(f"  {n:3d} -> ru: {titles['ru']:20s} en: {titles['en']:22s} fr: {titles['fr']}")

    return failures


async def cleanup(pool) -> None:
    await pool.execute("DELETE FROM workouts WHERE user_id = $1", TEST_USER_ID)
    await pool.execute("DELETE FROM user_streak_goals WHERE user_id = $1", TEST_USER_ID)
    await pool.execute("DELETE FROM user_settings WHERE user_id = $1", TEST_USER_ID)


async def insert_workout(pool, user_id: int, when: date, exercise: str = "жим лежа") -> None:
    await pool.execute(
        """
        INSERT INTO workouts (user_id, exercise_name, weight, reps, sets, created_at)
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        user_id, exercise, 80.0, 8, 3, when.isoformat() + "T18:00:00",
    )


async def test_real_end_to_end() -> list:
    print("\n" + "=" * 70)
    print("ЧАСТЬ 2: реальный сквозной прогон (БД + api.get_streak напрямую)")
    print("=" * 70)
    failures = []

    await init_db()
    pool = await get_pool()

    existing = await pool.fetchrow("SELECT 1 FROM workouts WHERE user_id = $1", TEST_USER_ID)
    if existing:
        print(f"СТОП: тестовый user_id {TEST_USER_ID} уже используется в БД")
        await close_pool()
        return [f"user_id {TEST_USER_ID} уже занят"]

    try:
        today = date.today()
        end_evaluation = today - timedelta(days=1)  # вчера — заведомо прошедший день, никакого "ещё не наступил"
        start_window = end_evaluation - timedelta(days=20)  # ровно 3 полные недели (21 день) до вчера включительно

        scheduled = streak_goals._scheduled_dates_between({1, 3, 5}, start_window, end_evaluation)
        print(f"Тестовое окно: {start_window} .. {end_evaluation}, запланированных дней: {len(scheduled)}")
        if len(scheduled) != 9:
            failures.append(f"Ожидалось ровно 9 запланированных дней (3 недели x 3), получено {len(scheduled)}")

        telegram_user = {"id": TEST_USER_ID}

        # --- Шаг 1: ВСЕ 9 запланированных дат за 3 недели заполнены без пропусков ---
        # (важно: окно калибровано так, чтобы заканчиваться ровно "вчера" — иначе более
        # поздние, уже прошедшие, но незаполненные даты внутри окна тоже считались бы
        # пропуском и сразу обнуляли бы streak, см. находку при первом прогоне этого теста)
        for d in scheduled:
            await insert_workout(pool, TEST_USER_ID, d)

        await pool.execute(
            "INSERT INTO user_streak_goals (user_id, target_weekdays, schedule_set_at) VALUES ($1, $2, $3)",
            TEST_USER_ID, [1, 3, 5], scheduled[0].isoformat(),
        )

        response1 = await api.get_streak(user_id=TEST_USER_ID, telegram_user=telegram_user)
        print(f"\nПосле 3 недель без пропусков (9 реальных записей): current_streak={response1.current_streak} "
              f"longest_streak={response1.longest_streak} total_workout_days={response1.total_workout_days} "
              f"rank={response1.rank_title!r}")
        if response1.current_streak != 9:
            failures.append(f"Ожидалось current_streak=9 после 3 недель, получено {response1.current_streak}")
        if response1.longest_streak != 9:
            failures.append(f"Ожидалось longest_streak=9, получено {response1.longest_streak}")

        # --- Шаг 2: удаляем запись за СРЕДНИЙ запланированный день (индекс 4 из 9) —
        # симулируем реальный пропущенный день тренировки посреди уже набранной серии ---
        missed_date = scheduled[4]
        await pool.execute(
            "DELETE FROM workouts WHERE user_id = $1 AND created_at LIKE $2",
            TEST_USER_ID, f"{missed_date.isoformat()}%",
        )

        response2 = await api.get_streak(user_id=TEST_USER_ID, telegram_user=telegram_user)
        # до пропуска (индексы 0-3) было 4 дня подряд, после (индексы 5-8) — тоже 4
        print(f"После удаления записи за пропущенный день {missed_date}: current_streak={response2.current_streak} "
              f"(ожидаем 4 — дни после пропуска) longest_streak={response2.longest_streak} (ожидаем 4)")
        if response2.current_streak != 4:
            failures.append(f"Ожидалось current_streak=4 после пропуска, получено {response2.current_streak}")
        if response2.longest_streak != 4:
            failures.append(f"Ожидалось longest_streak=4, получено {response2.longest_streak}")

        # --- Проверка звания по общему числу тренировок (осталось 8 записей после удаления) ---
        total = await pool.fetchval("SELECT COUNT(*) FROM workouts WHERE user_id = $1", TEST_USER_ID)
        print(f"\nВсего записей тренировок у тестового пользователя: {total}, звание: {response2.rank_title!r}")
        if total != 8:
            failures.append(f"Ожидалось 8 записей тренировок после удаления пропущенного дня, в БД оказалось {total}")

        # --- Проверка ленивого дефолта: другой тестовый user_id БЕЗ явного расписания ---
        default_user_id = TEST_USER_ID + 1
        await pool.execute("DELETE FROM workouts WHERE user_id = $1", default_user_id)
        await pool.execute("DELETE FROM user_streak_goals WHERE user_id = $1", default_user_id)
        response_default = await api.get_streak(user_id=default_user_id, telegram_user={"id": default_user_id})
        print(f"\nПользователь без явного расписания (дефолт): target_weekdays={response_default.target_weekdays} "
              f"(ожидаем [1, 3, 5] — нет профиля/сплита -> fallback)")
        if response_default.target_weekdays != [1, 3, 5]:
            failures.append(f"Ожидался дефолт [1, 3, 5], получено {response_default.target_weekdays}")
        await pool.execute("DELETE FROM user_streak_goals WHERE user_id = $1", default_user_id)

    finally:
        await cleanup(pool)
        verify_workouts = await pool.fetchrow("SELECT 1 FROM workouts WHERE user_id = $1", TEST_USER_ID)
        verify_goal = await pool.fetchrow("SELECT 1 FROM user_streak_goals WHERE user_id = $1", TEST_USER_ID)
        print(f"\nПосле cleanup: workouts={'осталось' if verify_workouts else 'чисто'}, "
              f"user_streak_goals={'осталось' if verify_goal else 'чисто'}")
        await close_pool()

    return failures


async def main() -> None:
    failures = test_pure_compute_streak()
    failures += await test_real_end_to_end()

    print("\n" + "=" * 70)
    if failures:
        print(f"НАЙДЕНО ПРОБЛЕМ: {len(failures)}")
        for f in failures:
            print(f"  !!! {f}")
    else:
        print("OK — все проверки прошли успешно.")


if __name__ == "__main__":
    asyncio.run(main())
