"""
Одноразовый тестовый скрипт: проверяет /start для УЖЕ зарегистрированного пользователя
(язык сохранён в БД заранее, минуя онбординг) — реальный вызов handlers.cmd_start и
handlers.handle_update_profile_cta, реальная БД, только Telegram-транспорт заглушен
(FakeMessage/FakeCallbackQuery, как в test_onboarding_flow.py), т.к. реального чата
отправить некуда.

Проверяет два момента: 1) раньше эта ветка cmd_start отправляла только голое минимальное
приветствие и больше ничего — теперь должна дополнительно показывать короткую подсказку
"продолжай как обычно" с inline-кнопкой "Обновить профиль"; 2) нажатие этой кнопки должно
запускать тот же мини-опрос профиля, что и обычная команда /update_profile (переиспользует
_start_profile_survey напрямую, см. handlers.handle_update_profile_cta).

Использует временный тестовый user_id (900000000501), удаляет его данные после теста.

Запуск: ./venv/bin/python scripts/test_repeat_start.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.base import StorageKey

import handlers
from database import close_pool, get_pool, init_db, set_user_language

TEST_USER_ID = 900000000501
BOT_ID = 1


class FakeUser:
    def __init__(self, user_id: int, full_name: str = "Постоянный Пользователь", language_code: str = "ru"):
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


class FakeCallbackQuery:
    def __init__(self, data: str, user: FakeUser, message: FakeMessage):
        self.data = data
        self.from_user = user
        self.message = message

    async def answer(self):
        pass


def has_inline_button_with_callback(reply_markup, callback_data: str) -> bool:
    if reply_markup is None:
        return False
    for row in reply_markup.inline_keyboard:
        for button in row:
            if getattr(button, "callback_data", None) == callback_data:
                return True
    return False


async def cleanup(pool) -> None:
    await pool.execute("DELETE FROM user_settings WHERE user_id = $1", TEST_USER_ID)
    await pool.execute("DELETE FROM user_fitness_profile WHERE user_id = $1", TEST_USER_ID)


async def main() -> None:
    await init_db()
    pool = await get_pool()

    existing_settings = await pool.fetchrow("SELECT 1 FROM user_settings WHERE user_id = $1", TEST_USER_ID)
    existing_profile = await pool.fetchrow("SELECT 1 FROM user_fitness_profile WHERE user_id = $1", TEST_USER_ID)
    if existing_settings or existing_profile:
        print(f"СТОП: тестовый user_id {TEST_USER_ID} уже используется в БД")
        await close_pool()
        return

    try:
        # Симулируем уже зарегистрированного пользователя: язык сохранён заранее,
        # минуя онбординг (как у реального пользователя, который проходил его раньше).
        await set_user_language(TEST_USER_ID, "ru")

        user = FakeUser(TEST_USER_ID)
        log: list = []
        storage = MemoryStorage()
        key = StorageKey(bot_id=BOT_ID, chat_id=TEST_USER_ID, user_id=TEST_USER_ID)
        state = FSMContext(storage=storage, key=key)

        msg = FakeMessage("/start", user, log)
        await handlers.cmd_start(msg, state)

        print("=== Шаг 1: /start (язык уже сохранён) ===")
        for entry in log:
            print(f"[{entry['type']}] reply_markup={'да' if entry['reply_markup'] else 'нет'}")
            print(entry["text"])
            print("---")

        failures = []
        if len(log) != 1:
            failures.append(f"Ожидалось ровно 1 сообщение, получено {len(log)}")
        else:
            entry = log[0]
            if entry["reply_markup"] is None:
                failures.append("К сообщению не прикреплена клавиатура")
            elif not has_inline_button_with_callback(entry["reply_markup"], "update_profile_cta"):
                failures.append("К сообщению не прикреплена inline-кнопка 'Обновить профиль'")
            if "LiftMate" not in entry["text"]:
                failures.append("В тексте нет упоминания LiftMate (приветствие пропало?)")
            if len(entry["text"].strip()) < 40:
                failures.append(f"Текст выглядит слишком коротким/голым: {entry['text']!r}")
        log.clear()

        # Шаг 2: нажимаем кнопку "Обновить профиль"
        callback_msg = FakeMessage("", user, log)
        callback = FakeCallbackQuery("update_profile_cta", user, callback_msg)
        await handlers.handle_update_profile_cta(callback, state)

        print("\n=== Шаг 2: нажатие кнопки 'Обновить профиль' -> должен запуститься опрос профиля ===")
        for entry in log:
            print(f"[{entry['type']}] {entry['text'][:150]!r}")

        if len(log) != 2:
            failures.append(f"Ожидалось 2 записи после нажатия кнопки (подтверждение + первый вопрос опроса), получено {len(log)}")
        else:
            confirm, survey_start = log[0], log[1]
            if confirm["type"] != "edit_text" or "обновить профиль" not in confirm["text"].lower():
                failures.append(f"Не похоже на подтверждение нажатия кнопки: {confirm}")
            if "стаж" not in survey_start["text"].lower() and "месяц" not in survey_start["text"].lower():
                failures.append(f"Не похоже на вопрос про стаж (начало обычного /update_profile опроса): {survey_start['text']!r}")

        current_state = await state.get_state()
        print(f"\nFSM-состояние после нажатия кнопки: {current_state}")
        if current_state != "ProfileStates:waiting_for_experience":
            failures.append(f"Ожидалось состояние ProfileStates:waiting_for_experience, получено {current_state}")

        print("\n" + "=" * 70)
        if failures:
            print(f"НАЙДЕНО ПРОБЛЕМ: {len(failures)}")
            for f in failures:
                print(f"  !!! {f}")
        else:
            print("OK — повторный /start показывает приветствие+подсказку+кнопку, кнопка запускает опрос профиля /update_profile.")

    finally:
        await cleanup(pool)
        verify_settings = await pool.fetchrow("SELECT 1 FROM user_settings WHERE user_id = $1", TEST_USER_ID)
        verify_profile = await pool.fetchrow("SELECT 1 FROM user_fitness_profile WHERE user_id = $1", TEST_USER_ID)
        print(f"\nПосле cleanup: user_settings={'осталось' if verify_settings else 'чисто'}, "
              f"user_fitness_profile={'осталось' if verify_profile else 'чисто'}")
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
