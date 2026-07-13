"""
Работа с базой данных PostgreSQL (asyncpg): хранение записей о тренировках.

Бот (main.py) и API-сервер (api.py) — два ОТДЕЛЬНЫХ процесса (в т.ч. на разных серверах
Railway), но оба читают/пишут в одну и ту же PostgreSQL базу через DATABASE_URL — это и
даёт им общее состояние (в отличие от файла liftmate.db, который был виден только внутри
одного процесса/сервера).

Каждый процесс держит свой собственный пул соединений (см. get_pool) — это нормально и
рекомендуемо для asyncpg, пул создаётся лениво при первом обращении к базе.
"""

import logging
from datetime import date, datetime
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

import asyncpg

from config import DATABASE_URL

logger = logging.getLogger("liftmate.database")

_pool: Optional[asyncpg.Pool] = None


def redact_database_url(url: str) -> str:
    """
    Прячет пароль из строки подключения — чтобы можно было безопасно залогировать
    (или показать в /debug_db), к какому именно хосту/базе идёт подключение, не
    засвечивая пароль. Полезно, чтобы сравнить, действительно ли бот и API смотрят
    в один и тот же DATABASE_URL (см. cmd_debug_db в handlers.py).
    """
    try:
        parsed = urlsplit(url)
        netloc = parsed.netloc
        if "@" in netloc:
            creds, host = netloc.rsplit("@", 1)
            user = creds.split(":", 1)[0]
            netloc = f"{user}:***@{host}"
        return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))
    except Exception:
        return "<не удалось разобрать DATABASE_URL>"


async def get_pool() -> asyncpg.Pool:
    """Возвращает общий пул подключений к PostgreSQL, создавая его при первом обращении."""
    global _pool
    if _pool is None:
        logger.info("Создаю пул подключений к PostgreSQL: %s", redact_database_url(DATABASE_URL))
        _pool = await asyncpg.create_pool(DATABASE_URL)
        logger.info("Пул подключений к PostgreSQL создан")
    return _pool


async def close_pool() -> None:
    """Аккуратно закрывает пул подключений (вызывать при штатном завершении процесса)."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def init_db() -> None:
    """Создаёт таблицы workouts, custom_exercises, user_settings и user_stats, если их ещё нет."""
    pool = await get_pool()

    await pool.execute(
        """
        CREATE TABLE IF NOT EXISTS workouts (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            exercise_name TEXT NOT NULL,
            weight REAL NOT NULL,
            reps INTEGER NOT NULL,
            sets INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    await pool.execute(
        """
        CREATE TABLE IF NOT EXISTS custom_exercises (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            exercise_name TEXT NOT NULL,
            category TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    await pool.execute(
        """
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id BIGINT PRIMARY KEY,
            language TEXT NOT NULL
        )
        """
    )
    # Статистика для лидербордов. current_streak/longest_streak/last_workout_date
    # обслуживают ЭТАП 1 (бесплатный глобальный лидерборд по сериям); is_premium
    # уже здесь для будущих platных лидербордов (по весу/% прогресса) — достаточно
    # будет читать этот же флаг, не меняя схему.
    await pool.execute(
        """
        CREATE TABLE IF NOT EXISTS user_stats (
            user_id BIGINT PRIMARY KEY,
            current_streak INTEGER NOT NULL DEFAULT 0,
            longest_streak INTEGER NOT NULL DEFAULT 0,
            last_workout_date TEXT,
            is_premium INTEGER NOT NULL DEFAULT 0
        )
        """
    )


async def get_last_workout(user_id: int, exercise_name: str) -> Optional[dict]:
    """
    Возвращает последнюю запись пользователя по данному упражнению (или None, если записей ещё не было).

    Совпадение по exercise_name — БЕЗ учёта регистра и пробелов по краям
    (LOWER(TRIM(...)) с обеих сторон), а не точное "=". Раньше было точное совпадение,
    и из-за этого запись, сохранённая как "Bench Press" или "bench press " (с лишним
    пробелом на конце — такое встречается, если название пришло из свободного текста
    через GPT, а не из фиксированного списка exercises_data.py), просто не находилась
    при поиске по нормализованному "bench press".
    """
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT * FROM workouts
        WHERE user_id = $1 AND LOWER(TRIM(exercise_name)) = LOWER(TRIM($2))
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        user_id,
        exercise_name,
    )
    return dict(row) if row else None


async def get_workout_history(user_id: int, exercise_name: str) -> list:
    """
    Возвращает всю историю тренировок пользователя по данному упражнению, от самой
    старой к самой новой (для графика прогресса в Web App). Пустой список, если
    записей нет — это не ошибка, а нормальный случай для нового упражнения.

    Совпадение по exercise_name — без учёта регистра и пробелов по краям, см. docstring
    get_last_workout выше — та же проблема была и здесь.
    """
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT * FROM workouts
        WHERE user_id = $1 AND LOWER(TRIM(exercise_name)) = LOWER(TRIM($2))
        ORDER BY created_at ASC, id ASC
        """,
        user_id,
        exercise_name,
    )
    return [dict(row) for row in rows]


async def add_workout(
    user_id: int,
    exercise_name: str,
    weight: float,
    reps: int,
    sets: int,
) -> None:
    """
    Сохраняет новую запись о тренировке в базу данных.

    exercise_name дополнительно нормализуется (strip + lower) прямо здесь, в единой
    точке записи — это подстраховка на случай, если какой-то вызывающий код (сейчас
    или в будущем) забудет это сделать сам, чтобы в базе не копился разнобой вроде
    "Bench Press" / "bench press " / "bench press". Поиск (get_last_workout,
    get_workout_history) всё равно сравнивает без учёта регистра/пробелов — это
    защита от НОВОГО разнобоя, а не замена той защите для уже старых записей.

    Логирует ПЕРЕД попыткой INSERT (что именно пытаемся сохранить) и ПОСЛЕ (id новой
    записи при успехе, либо полный traceback при ошибке — исключение не глотается,
    а пробрасывается дальше как и раньше, просто теперь ещё и явно видно в логах).
    """
    exercise_name = exercise_name.strip().lower()
    created_at = datetime.now().isoformat()
    logger.info(
        "add_workout: пытаюсь сохранить user_id=%s exercise_name=%r weight=%s reps=%s sets=%s created_at=%s",
        user_id, exercise_name, weight, reps, sets, created_at,
    )

    try:
        pool = await get_pool()
        new_id = await pool.fetchval(
            """
            INSERT INTO workouts (user_id, exercise_name, weight, reps, sets, created_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            user_id,
            exercise_name,
            weight,
            reps,
            sets,
            created_at,
        )
    except Exception:
        logger.exception(
            "add_workout: ОШИБКА при сохранении user_id=%s exercise_name=%r — запись НЕ сохранена!",
            user_id, exercise_name,
        )
        raise

    logger.info("add_workout: успешно сохранено, id новой записи в workouts = %s", new_id)


async def count_all_workouts() -> int:
    """
    Прямой SELECT COUNT(*) FROM workouts по всей таблице (все пользователи) — простая
    диагностика для /debug_db: если тут 0 (или число не растёт после записи тренировки),
    значит данные реально не попадают в эту базу, а не просто "не находятся" фильтром.
    """
    pool = await get_pool()
    return await pool.fetchval("SELECT COUNT(*) FROM workouts")


async def count_user_workouts(user_id: int) -> int:
    """То же самое, но только для одного пользователя — для /debug_db."""
    pool = await get_pool()
    return await pool.fetchval("SELECT COUNT(*) FROM workouts WHERE user_id = $1", user_id)


async def get_recent_workouts(user_id: int, limit: int = 5) -> list:
    """
    Последние N записей пользователя (любое упражнение), от новой к старой — для /debug_db.
    Специально возвращает exercise_name КАК ОН ЕСТЬ в базе, без нормализации — именно
    чтобы можно было увидеть лишние пробелы/регистр вживую, а не после их устранения.
    """
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT * FROM workouts
        WHERE user_id = $1
        ORDER BY created_at DESC, id DESC
        LIMIT $2
        """,
        user_id,
        limit,
    )
    return [dict(row) for row in rows]


async def get_last_workout_for_user(user_id: int) -> Optional[dict]:
    """
    Возвращает самую последнюю запись пользователя (любое упражнение).

    Используется как "якорь", когда пользователь дополняет или поправляет уже
    обсуждённый подход (например, "сделал ещё один подход"), а не описывает новый.
    """
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT * FROM workouts
        WHERE user_id = $1
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        user_id,
    )
    return dict(row) if row else None


async def update_workout_by_id(workout_id: int, weight: float, reps: int, sets: int) -> None:
    """Обновляет уже существующую запись о тренировке новыми абсолютными значениями."""
    pool = await get_pool()
    await pool.execute(
        "UPDATE workouts SET weight = $1, reps = $2, sets = $3 WHERE id = $4",
        weight,
        reps,
        sets,
        workout_id,
    )


async def add_custom_exercise(user_id: int, exercise_name: str, category: str) -> int:
    """Сохраняет упражнение, добавленное пользователем вручную через меню. Возвращает его id."""
    pool = await get_pool()
    new_id = await pool.fetchval(
        """
        INSERT INTO custom_exercises (user_id, exercise_name, category, created_at)
        VALUES ($1, $2, $3, $4)
        RETURNING id
        """,
        user_id,
        exercise_name,
        category,
        datetime.now().isoformat(),
    )
    return new_id


async def get_custom_exercises(user_id: int, category: str) -> list:
    """Возвращает пользовательские упражнения этой категории (для отображения в меню)."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT * FROM custom_exercises
        WHERE user_id = $1 AND category = $2
        ORDER BY created_at ASC
        """,
        user_id,
        category,
    )
    return [dict(row) for row in rows]


async def get_custom_exercise_by_id(custom_exercise_id: int) -> Optional[dict]:
    """Возвращает пользовательское упражнение по его id (для обработки нажатия кнопки)."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM custom_exercises WHERE id = $1",
        custom_exercise_id,
    )
    return dict(row) if row else None


async def get_user_language(user_id: int) -> Optional[str]:
    """Возвращает явно выбранный пользователем язык интерфейса, либо None, если ещё не выбран."""
    pool = await get_pool()
    return await pool.fetchval(
        "SELECT language FROM user_settings WHERE user_id = $1",
        user_id,
    )


async def set_user_language(user_id: int, language: str) -> None:
    """Сохраняет (или обновляет) явно выбранный пользователем язык интерфейса."""
    pool = await get_pool()
    await pool.execute(
        """
        INSERT INTO user_settings (user_id, language)
        VALUES ($1, $2)
        ON CONFLICT (user_id) DO UPDATE SET language = excluded.language
        """,
        user_id,
        language,
    )


async def get_user_stats(user_id: int) -> Optional[dict]:
    """Возвращает статистику пользователя (серии, is_premium), либо None, если он ещё не тренировался."""
    pool = await get_pool()
    row = await pool.fetchrow("SELECT * FROM user_stats WHERE user_id = $1", user_id)
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
    pool = await get_pool()

    row = await pool.fetchrow(
        "SELECT current_streak, longest_streak, last_workout_date FROM user_stats WHERE user_id = $1",
        user_id,
    )

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

    await pool.execute(
        """
        INSERT INTO user_stats (user_id, current_streak, longest_streak, last_workout_date, is_premium)
        VALUES ($1, $2, $3, $4, 0)
        ON CONFLICT (user_id) DO UPDATE SET
            current_streak = excluded.current_streak,
            longest_streak = excluded.longest_streak,
            last_workout_date = excluded.last_workout_date
        """,
        user_id,
        current_streak,
        longest_streak,
        today.isoformat(),
    )

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
    pool = await get_pool()

    if user_ids:
        # asyncpg использует позиционные плейсхолдеры $1, $2... — под них нужно
        # сгенерировать ровно столько же меток, сколько элементов в user_ids,
        # а $N для LIMIT идёт следующим номером после них
        placeholders = ", ".join(f"${i + 1}" for i in range(len(user_ids)))
        query = f"""
            SELECT user_id, current_streak, longest_streak FROM user_stats
            WHERE current_streak > 0 AND user_id IN ({placeholders})
            ORDER BY current_streak DESC, longest_streak DESC, user_id ASC
            LIMIT ${len(user_ids) + 1}
        """
        rows = await pool.fetch(query, *user_ids, limit)
    else:
        query = """
            SELECT user_id, current_streak, longest_streak FROM user_stats
            WHERE current_streak > 0
            ORDER BY current_streak DESC, longest_streak DESC, user_id ASC
            LIMIT $1
        """
        rows = await pool.fetch(query, limit)

    return [dict(row) for row in rows]


async def get_user_rank(user_id: int, user_ids: Optional[list] = None) -> Optional[dict]:
    """
    Возвращает место пользователя в рейтинге по текущей серии — {"rank", "current_streak"},
    либо None, если у пользователя ещё нет ни одной записи в user_stats. Место считается
    по числу пользователей со строго большей серией (+1), поэтому равные серии делят место.

    user_ids — тот же опциональный фильтр под будущие дружеские лидерборды, что и в
    get_leaderboard_top (без него — место в глобальном рейтинге).
    """
    pool = await get_pool()

    current_streak = await pool.fetchval(
        "SELECT current_streak FROM user_stats WHERE user_id = $1", user_id
    )
    if current_streak is None:
        return None

    if user_ids:
        # $1 — сам current_streak, дальше $2, $3... под user_ids
        placeholders = ", ".join(f"${i + 2}" for i in range(len(user_ids)))
        query = f"""
            SELECT COUNT(*) FROM user_stats
            WHERE current_streak > $1 AND user_id IN ({placeholders})
        """
        higher_count = await pool.fetchval(query, current_streak, *user_ids)
    else:
        higher_count = await pool.fetchval(
            "SELECT COUNT(*) FROM user_stats WHERE current_streak > $1", current_streak
        )

    return {"rank": higher_count + 1, "current_streak": current_streak}
