"""Работа с базой данных SQLite: хранение записей о тренировках."""

from datetime import date, datetime
from typing import Optional

import aiosqlite

DB_PATH = "liftmate.db"


async def init_db() -> None:
    """Создаёт таблицы workouts, custom_exercises, user_settings и user_stats, если их ещё нет."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS workouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                exercise_name TEXT NOT NULL,
                weight REAL NOT NULL,
                reps INTEGER NOT NULL,
                sets INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS custom_exercises (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                exercise_name TEXT NOT NULL,
                category TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                language TEXT NOT NULL
            )
            """
        )
        # Статистика для лидербордов. current_streak/longest_streak/last_workout_date
        # обслуживают ЭТАП 1 (бесплатный глобальный лидерборд по сериям); is_premium
        # уже здесь для будущих platных лидербордов (по весу/% прогресса) — достаточно
        # будет читать этот же флаг, не меняя схему.
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS user_stats (
                user_id INTEGER PRIMARY KEY,
                current_streak INTEGER NOT NULL DEFAULT 0,
                longest_streak INTEGER NOT NULL DEFAULT 0,
                last_workout_date TEXT,
                is_premium INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        await db.commit()


async def get_last_workout(user_id: int, exercise_name: str) -> Optional[dict]:
    """Возвращает последнюю запись пользователя по данному упражнению (или None, если записей ещё не было)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM workouts
            WHERE user_id = ? AND exercise_name = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (user_id, exercise_name),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_workout_history(user_id: int, exercise_name: str) -> list:
    """
    Возвращает всю историю тренировок пользователя по данному упражнению, от самой
    старой к самой новой (для графика прогресса в Web App). Пустой список, если
    записей нет — это не ошибка, а нормальный случай для нового упражнения.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM workouts
            WHERE user_id = ? AND exercise_name = ?
            ORDER BY created_at ASC, id ASC
            """,
            (user_id, exercise_name),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def add_workout(
    user_id: int,
    exercise_name: str,
    weight: float,
    reps: int,
    sets: int,
) -> None:
    """Сохраняет новую запись о тренировке в базу данных."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO workouts (user_id, exercise_name, weight, reps, sets, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, exercise_name, weight, reps, sets, datetime.now().isoformat()),
        )
        await db.commit()


async def get_last_workout_for_user(user_id: int) -> Optional[dict]:
    """
    Возвращает самую последнюю запись пользователя (любое упражнение).

    Используется как "якорь", когда пользователь дополняет или поправляет уже
    обсуждённый подход (например, "сделал ещё один подход"), а не описывает новый.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM workouts
            WHERE user_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (user_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def update_workout_by_id(workout_id: int, weight: float, reps: int, sets: int) -> None:
    """Обновляет уже существующую запись о тренировке новыми абсолютными значениями."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE workouts SET weight = ?, reps = ?, sets = ? WHERE id = ?",
            (weight, reps, sets, workout_id),
        )
        await db.commit()


async def add_custom_exercise(user_id: int, exercise_name: str, category: str) -> int:
    """Сохраняет упражнение, добавленное пользователем вручную через меню. Возвращает его id."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO custom_exercises (user_id, exercise_name, category, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, exercise_name, category, datetime.now().isoformat()),
        )
        await db.commit()
        return cursor.lastrowid


async def get_custom_exercises(user_id: int, category: str) -> list:
    """Возвращает пользовательские упражнения этой категории (для отображения в меню)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM custom_exercises
            WHERE user_id = ? AND category = ?
            ORDER BY created_at ASC
            """,
            (user_id, category),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_custom_exercise_by_id(custom_exercise_id: int) -> Optional[dict]:
    """Возвращает пользовательское упражнение по его id (для обработки нажатия кнопки)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM custom_exercises WHERE id = ?",
            (custom_exercise_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_user_language(user_id: int) -> Optional[str]:
    """Возвращает явно выбранный пользователем язык интерфейса, либо None, если ещё не выбран."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT language FROM user_settings WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        return row[0] if row else None


async def set_user_language(user_id: int, language: str) -> None:
    """Сохраняет (или обновляет) явно выбранный пользователем язык интерфейса."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO user_settings (user_id, language)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET language = excluded.language
            """,
            (user_id, language),
        )
        await db.commit()


async def get_user_stats(user_id: int) -> Optional[dict]:
    """Возвращает статистику пользователя (серии, is_premium), либо None, если он ещё не тренировался."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM user_stats WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def update_streak_on_workout(user_id: int, today: Optional[date] = None) -> dict:
    """
    Обновляет серию тренировок пользователя при записи НОВОГО подхода (вызывается один
    раз на новую запись, а не на правки уже существующей — см. handlers._save_and_reply).

    Логика:
    - нет предыдущей тренировки (первая запись вообще) -> серия начинается с 1
    - предыдущая тренировка была вчера -> новый день подряд, серия +1
    - предыдущая тренировка была сегодня же -> тот же день, серия не меняется
    - между тренировками был пропуск в 2+ дня -> серия сбрасывается на 1

    longest_streak обновляется, если текущая серия его превысила. Возвращает итоговые
    {"current_streak", "longest_streak", "last_workout_date"}.
    """
    today = today or date.today()

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT current_streak, longest_streak, last_workout_date FROM user_stats WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()

        if row is None:
            current_streak = 1
            longest_streak = 1
        else:
            current_streak = row["current_streak"]
            longest_streak = row["longest_streak"]
            last_date = date.fromisoformat(row["last_workout_date"]) if row["last_workout_date"] else None

            if last_date is None:
                current_streak = 1
            else:
                gap = (today - last_date).days
                if gap <= 0:
                    pass  # та же дата (или сдвиг часов назад) — серия не меняется
                elif gap == 1:
                    current_streak += 1
                else:
                    current_streak = 1  # пропустили день и больше — серия сбрасывается

            longest_streak = max(longest_streak, current_streak)

        await db.execute(
            """
            INSERT INTO user_stats (user_id, current_streak, longest_streak, last_workout_date, is_premium)
            VALUES (?, ?, ?, ?, 0)
            ON CONFLICT(user_id) DO UPDATE SET
                current_streak = excluded.current_streak,
                longest_streak = excluded.longest_streak,
                last_workout_date = excluded.last_workout_date
            """,
            (user_id, current_streak, longest_streak, today.isoformat()),
        )
        await db.commit()

        return {
            "current_streak": current_streak,
            "longest_streak": longest_streak,
            "last_workout_date": today.isoformat(),
        }


async def get_leaderboard_top(limit: int = 10, user_ids: Optional[list] = None) -> list:
    """
    Возвращает топ пользователей по текущей серии (current_streak), по убыванию.

    user_ids — опциональный фильтр по конкретному подмножеству пользователей: задел
    на будущие дружеские лидерборды (передать id участников группы). Без него —
    глобальный топ по всем пользователям.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if user_ids:
            placeholders = ",".join("?" for _ in user_ids)
            query = f"""
                SELECT user_id, current_streak, longest_streak FROM user_stats
                WHERE current_streak > 0 AND user_id IN ({placeholders})
                ORDER BY current_streak DESC, longest_streak DESC, user_id ASC
                LIMIT ?
            """
            params = (*user_ids, limit)
        else:
            query = """
                SELECT user_id, current_streak, longest_streak FROM user_stats
                WHERE current_streak > 0
                ORDER BY current_streak DESC, longest_streak DESC, user_id ASC
                LIMIT ?
            """
            params = (limit,)

        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_user_rank(user_id: int, user_ids: Optional[list] = None) -> Optional[dict]:
    """
    Возвращает место пользователя в рейтинге по текущей серии — {"rank", "current_streak"},
    либо None, если у пользователя ещё нет ни одной записи в user_stats. Место считается
    по числу пользователей со строго большей серией (+1), поэтому равные серии делят место.

    user_ids — тот же опциональный фильтр под будущие дружеские лидерборды, что и в
    get_leaderboard_top (без него — место в глобальном рейтинге).
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT current_streak FROM user_stats WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        current_streak = row["current_streak"]

        if user_ids:
            placeholders = ",".join("?" for _ in user_ids)
            query = f"""
                SELECT COUNT(*) FROM user_stats
                WHERE current_streak > ? AND user_id IN ({placeholders})
            """
            params = (current_streak, *user_ids)
        else:
            query = "SELECT COUNT(*) FROM user_stats WHERE current_streak > ?"
            params = (current_streak,)

        cursor = await db.execute(query, params)
        row = await cursor.fetchone()
        higher_count = row[0]

        return {"rank": higher_count + 1, "current_streak": current_streak}
