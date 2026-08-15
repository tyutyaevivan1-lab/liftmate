"""
Одноразовый тестовый скрипт — два независимых прогона поверх сегодняшних изменений в
системе streak (см. handlers.py: cmd_schedule/handle_schedule_toggle/handle_schedule_done,
api.py: GET /api/user/{user_id}/streak):

ЧАСТЬ 1: реальный прогон toggle-клавиатуры выбора дней недели через настоящие обработчики
handlers.py — /schedule -> несколько тапов по дням (переключение чекмарок) -> "Готово" ->
проверяем, что в БД (user_streak_goals) сохранился именно тот набор дней, что был отмечен
на момент нажатия "Готово", и что api.get_streak после этого считает streak уже по новому
расписанию. Telegram-транспорт заглушен (FakeMessage/FakeCallbackQuery, как в предыдущих
тестах этого проекта) — реального чата отправить некуда, вся остальная логика настоящая
(FSM через aiogram MemoryStorage, реальная БД).

ЧАСТЬ 2: проверка исправления бага total_workout_days — пользователь с 9 записями подходов,
но ВСЕМИ в один и тот же календарный день, должен получить звание, соответствующее ИМЕННО
1 тренировочному дню (низший порог, "Новичок"), а не 9 записям (что раньше ошибочно давало
более высокое звание).

Использует временные тестовые user_id (900000000701, 900000000702), удаляет все их данные
после теста.

Запуск: ./venv/bin/python scripts/test_schedule_selection.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.base import StorageKey

import api
import handlers
import keyboards
from database import close_pool, get_pool, get_streak_goal, init_db

TOGGLE_USER_ID = 900000000701
RANK_BUG_USER_ID = 900000000702
BOT_ID = 1


class FakeUser:
    def __init__(self, user_id: int, full_name: str = "Тестовый Пользователь", language_code: str = "ru"):
        self.id = user_id
        self.full_name = full_name
        self.language_code = language_code


class FakeMessage:
    def __init__(self, text: str, user: FakeUser, log: list):
        self.text = text
        self.from_user = user
        self._log = log

    async def answer(self, text: str, reply_markup=None):
        self._log.append({"type": "answer", "text": text, "reply_markup": reply_markup})
        return FakeMessage(text, self.from_user, self._log)

    async def edit_text(self, text: str, reply_markup=None):
        self._log.append({"type": "edit_text", "text": text, "reply_markup": reply_markup})

    async def edit_reply_markup(self, reply_markup=None):
        self._log.append({"type": "edit_reply_markup", "text": None, "reply_markup": reply_markup})


class FakeCallbackQuery:
    def __init__(self, data: str, user: FakeUser, message: FakeMessage):
        self.data = data
        self.from_user = user
        self.message = message
        self.answer_calls = []

    async def answer(self, text: str = None, show_alert: bool = False):
        self.answer_calls.append({"text": text, "show_alert": show_alert})


def checked_weekdays(reply_markup) -> set:
    """Извлекает набор отмеченных (с чекмаркой) дней недели из клавиатуры build_schedule_keyboard."""
    checked = set()
    for row in reply_markup.inline_keyboard:
        for button in row:
            if button.callback_data and button.callback_data.startswith(f"{keyboards.SCHEDULE_TOGGLE_CALLBACK_PREFIX}:"):
                weekday = int(button.callback_data.split(":", 1)[1])
                if button.text.startswith("✅"):
                    checked.add(weekday)
    return checked


async def test_toggle_flow(pool) -> list:
    print("=" * 70)
    print("ЧАСТЬ 1: toggle-клавиатура /schedule через реальные обработчики")
    print("=" * 70)
    failures = []

    user = FakeUser(TOGGLE_USER_ID)
    log: list = []
    storage = MemoryStorage()
    key = StorageKey(bot_id=BOT_ID, chat_id=TOGGLE_USER_ID, user_id=TOGGLE_USER_ID)
    state = FSMContext(storage=storage, key=key)

    # Шаг 1: /schedule (нет ни профиля, ни расписания -> дефолт пн/ср/пт)
    msg = FakeMessage("/schedule", user, log)
    await handlers.cmd_schedule(msg, state)

    print("\n=== Шаг 1: /schedule (первый раз, дефолт) ===")
    for entry in log:
        print(f"  [{entry['type']}] {entry['text']!r}")
    if len(log) != 1:
        failures.append(f"Ожидалось 1 сообщение после /schedule, получено {len(log)}")
    else:
        initial_checked = checked_weekdays(log[0]["reply_markup"])
        print(f"  Изначально отмечены дни (ISO): {sorted(initial_checked)} (ожидаем дефолт [1, 3, 5])")
        if initial_checked != {1, 3, 5}:
            failures.append(f"Ожидался дефолт {{1, 3, 5}}, получено {initial_checked}")
    log.clear()

    # Шаг 2: тапаем по вторнику (2) -> должен добавиться к выбору
    callback_msg = FakeMessage("", user, log)
    callback_tue = FakeCallbackQuery(f"{keyboards.SCHEDULE_TOGGLE_CALLBACK_PREFIX}:2", user, callback_msg)
    await handlers.handle_schedule_toggle(callback_tue, state)

    print("\n=== Шаг 2: тап по вторнику (добавляем) ===")
    if log:
        checked_after_tue = checked_weekdays(log[-1]["reply_markup"])
        print(f"  Отмечены после тапа: {sorted(checked_after_tue)} (ожидаем [1, 2, 3, 5])")
        if checked_after_tue != {1, 2, 3, 5}:
            failures.append(f"Ожидалось {{1,2,3,5}} после добавления вторника, получено {checked_after_tue}")
    else:
        failures.append("Нет ответа после тапа по вторнику")
    log.clear()

    # Шаг 3: тапаем по понедельнику (1) -> должен убраться из выбора (снимаем чекмарку)
    callback_mon = FakeCallbackQuery(f"{keyboards.SCHEDULE_TOGGLE_CALLBACK_PREFIX}:1", user, callback_msg)
    await handlers.handle_schedule_toggle(callback_mon, state)

    print("\n=== Шаг 3: тап по понедельнику (убираем) ===")
    if log:
        checked_after_mon = checked_weekdays(log[-1]["reply_markup"])
        print(f"  Отмечены после тапа: {sorted(checked_after_mon)} (ожидаем [2, 3, 5])")
        if checked_after_mon != {2, 3, 5}:
            failures.append(f"Ожидалось {{2,3,5}} после снятия понедельника, получено {checked_after_mon}")
    else:
        failures.append("Нет ответа после тапа по понедельнику")
    log.clear()

    # Шаг 4: жмём "Готово" -> должно сохраниться {2, 3, 5} в БД
    callback_done = FakeCallbackQuery(keyboards.SCHEDULE_DONE_CALLBACK, user, callback_msg)
    await handlers.handle_schedule_done(callback_done, state)

    print("\n=== Шаг 4: нажатие 'Готово' ===")
    for entry in log:
        print(f"  [{entry['type']}] {entry['text']!r}")

    if len(log) != 1 or log[0]["type"] != "edit_text":
        failures.append(f"Ожидалось 1 edit_text после 'Готово', получено {log}")
    else:
        saved_text = log[0]["text"]
        if "вт" not in saved_text.lower() and "tue" not in saved_text.lower():
            failures.append(f"Текст подтверждения не упоминает вторник: {saved_text!r}")

    goal = await get_streak_goal(TOGGLE_USER_ID)
    print(f"\n  В БД сохранено: {goal}")
    if goal is None or set(goal["target_weekdays"]) != {2, 3, 5}:
        failures.append(f"Ожидалось target_weekdays={{2,3,5}} в БД, получено {goal}")

    current_state = await state.get_state()
    print(f"  FSM-состояние после 'Готово': {current_state} (ожидаем None)")
    if current_state is not None:
        failures.append(f"Ожидалось состояние None после сохранения, получено {current_state}")

    # Проверка: api.get_streak теперь использует именно это расписание
    response = await api.get_streak(user_id=TOGGLE_USER_ID, telegram_user={"id": TOGGLE_USER_ID})
    print(f"\n  api.get_streak после сохранения: target_weekdays={response.target_weekdays} (ожидаем [2, 3, 5])")
    if response.target_weekdays != [2, 3, 5]:
        failures.append(f"Ожидалось target_weekdays=[2,3,5] от API, получено {response.target_weekdays}")

    # Шаг 5: пустой выбор -> "Готово" без единого дня должно быть отклонено (алерт), без сохранения
    log.clear()
    msg2 = FakeMessage("/schedule", user, log)
    await handlers.cmd_schedule(msg2, state)
    log.clear()
    data = await state.get_data()
    for wd in list(data.get("selected_weekdays", [])):
        cb = FakeCallbackQuery(f"{keyboards.SCHEDULE_TOGGLE_CALLBACK_PREFIX}:{wd}", user, callback_msg)
        await handlers.handle_schedule_toggle(cb, state)
    log.clear()
    callback_done_empty = FakeCallbackQuery(keyboards.SCHEDULE_DONE_CALLBACK, user, callback_msg)
    await handlers.handle_schedule_done(callback_done_empty, state)

    print("\n=== Шаг 5: 'Готово' с пустым выбором (все дни сняты) ===")
    print(f"  callback.answer() вызовы: {callback_done_empty.answer_calls}")
    if not callback_done_empty.answer_calls or not callback_done_empty.answer_calls[0]["show_alert"]:
        failures.append("Ожидался алерт (show_alert=True) при пустом выборе")

    goal_after_empty_attempt = await get_streak_goal(TOGGLE_USER_ID)
    print(f"  Расписание в БД не должно было измениться: {goal_after_empty_attempt}")
    if goal_after_empty_attempt is None or set(goal_after_empty_attempt["target_weekdays"]) != {2, 3, 5}:
        failures.append(f"Пустой выбор не должен был перезаписать расписание, получено {goal_after_empty_attempt}")

    return failures


async def insert_workout(pool, user_id: int, when_iso: str, exercise: str) -> None:
    await pool.execute(
        """
        INSERT INTO workouts (user_id, exercise_name, weight, reps, sets, created_at)
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        user_id, exercise, 80.0, 8, 3, when_iso,
    )


async def test_rank_bug_fix(pool) -> list:
    print("\n" + "=" * 70)
    print("ЧАСТЬ 2: исправление бага total_workout_days (9 записей, 1 день)")
    print("=" * 70)
    failures = []

    same_day = "2026-08-10"
    exercises = ["жим лежа", "приседания", "тяга штанги", "жим гантелей", "подтягивания",
                 "разгибание рук", "сгибание рук", "выпады", "планка"]
    for i, ex in enumerate(exercises):
        await insert_workout(pool, RANK_BUG_USER_ID, f"{same_day}T{10 + i}:00:00", ex)

    total_rows = await pool.fetchval("SELECT COUNT(*) FROM workouts WHERE user_id = $1", RANK_BUG_USER_ID)
    print(f"Вставлено записей в БД: {total_rows} (все за один день {same_day})")

    response = await api.get_streak(user_id=RANK_BUG_USER_ID, telegram_user={"id": RANK_BUG_USER_ID})
    # язык тестовому пользователю не задавался -> api.py по умолчанию берёт "en" (см.
    # get_user_language(...) or "en"), поэтому проверяем англ. название низшего порога
    print(f"\napi.get_streak: total_workout_days={response.total_workout_days} (ожидаем 1, НЕ 9) "
          f"rank_title={response.rank_title!r} (ожидаем 'Beginner 🌱', порог для 1 дня)")

    if response.total_workout_days != 1:
        failures.append(f"Ожидалось total_workout_days=1 (один календарный день), получено {response.total_workout_days}")
    if "Beginner" not in response.rank_title:
        failures.append(f"Ожидалось звание 'Beginner 🌱' (порог 0-2 дня), получено {response.rank_title!r}")
    if total_rows != 9:
        failures.append(f"Ожидалось 9 записей в БД, получено {total_rows}")

    return failures


async def cleanup(pool) -> None:
    for user_id in (TOGGLE_USER_ID, RANK_BUG_USER_ID):
        await pool.execute("DELETE FROM workouts WHERE user_id = $1", user_id)
        await pool.execute("DELETE FROM user_streak_goals WHERE user_id = $1", user_id)
        await pool.execute("DELETE FROM user_settings WHERE user_id = $1", user_id)
        await pool.execute("DELETE FROM user_fitness_profile WHERE user_id = $1", user_id)


async def main() -> None:
    await init_db()
    pool = await get_pool()

    existing = await pool.fetch(
        "SELECT user_id FROM user_streak_goals WHERE user_id = ANY($1::bigint[])",
        [TOGGLE_USER_ID, RANK_BUG_USER_ID],
    )
    existing_workouts = await pool.fetch(
        "SELECT user_id FROM workouts WHERE user_id = ANY($1::bigint[])",
        [TOGGLE_USER_ID, RANK_BUG_USER_ID],
    )
    if existing or existing_workouts:
        print(f"СТОП: тестовые user_id уже используются в БД")
        await close_pool()
        return

    try:
        failures = await test_toggle_flow(pool)
        failures += await test_rank_bug_fix(pool)
    finally:
        await cleanup(pool)
        verify = await pool.fetch(
            "SELECT user_id FROM user_streak_goals WHERE user_id = ANY($1::bigint[])",
            [TOGGLE_USER_ID, RANK_BUG_USER_ID],
        )
        print(f"\nПосле cleanup осталось строк в user_streak_goals: {len(verify)} (ожидаем 0)")
        await close_pool()

    print("\n" + "=" * 70)
    if failures:
        print(f"НАЙДЕНО ПРОБЛЕМ: {len(failures)}")
        for f in failures:
            print(f"  !!! {f}")
    else:
        print("OK — все проверки прошли успешно.")


if __name__ == "__main__":
    asyncio.run(main())
