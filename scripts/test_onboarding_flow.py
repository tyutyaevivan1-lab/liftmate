"""
Одноразовый тестовый скрипт: реальный (без моков GPT/БД) прогон пересобранного онбординга
через настоящие обработчики handlers.py — cmd_start, handle_language_selected,
handle_profile_experience, handle_equipment_selected, handle_profile_equipment_details,
handle_limitations_none, handle_text_message — с настоящим aiogram FSMContext
(MemoryStorage) и настоящей БД.

Telegram Message/CallbackQuery — единственное, что здесь ЗАГЛУШЕНО (FakeMessage/
FakeCallbackQuery ниже): реального чата отправить некуда, поэтому .answer()/.edit_text()
просто записывают текст вместо реального HTTP-вызова к Telegram. Вся бизнес-логика
(парсинг, FSM-переходы, запись в БД, GPT-вызовы через parse_experience_months и
parse_workout_message) выполняется по-настоящему.

Проверяет: 1) минимальное приветствие /start до выбора языка; 2) сразу мини-опрос профиля
после выбора языка (без "погнали"); 3) переход в Web App (текст + inline-кнопка) сразу
после опроса, БЕЗ obычного profile_saved_text; 4) объяснение трекинга текстом показывается
ровно один раз — при первом свободном сообщении после онбординга, но не повторяется на
втором сообщении; 5) кнопки постоянного меню и "ещё один подход" нигде не объясняются
текстом.

Использует временный тестовый user_id (900000000401), удаляет все его данные после теста.

Запуск: ./venv/bin/python scripts/test_onboarding_flow.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.base import StorageKey

import handlers
import keyboards
from database import close_pool, get_pool, init_db

TEST_USER_ID = 900000000401
TEST_CHAT_ID = TEST_USER_ID
BOT_ID = 1  # произвольный, нужен только для StorageKey


class FakeUser:
    def __init__(self, user_id: int, full_name: str = "Тестовый Пользователь", language_code: str = "ru"):
        self.id = user_id
        self.full_name = full_name
        self.language_code = language_code


class FakeMessage:
    """Достаточно полей/методов, чтобы обработчики handlers.py отработали как в реальном боте."""

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


def make_state(log_label: str) -> FSMContext:
    storage = _SHARED_STORAGE
    key = StorageKey(bot_id=BOT_ID, chat_id=TEST_CHAT_ID, user_id=TEST_USER_ID)
    return FSMContext(storage=storage, key=key)


_SHARED_STORAGE = MemoryStorage()


def last_text(log: list) -> str:
    return log[-1]["text"]


def has_button_with_webapp(reply_markup) -> bool:
    if reply_markup is None:
        return False
    for row in reply_markup.inline_keyboard:
        for button in row:
            if getattr(button, "web_app", None) is not None:
                return True
    return False


async def cleanup(pool) -> None:
    await pool.execute("DELETE FROM user_settings WHERE user_id = $1", TEST_USER_ID)
    await pool.execute("DELETE FROM user_fitness_profile WHERE user_id = $1", TEST_USER_ID)
    await pool.execute("DELETE FROM workouts WHERE user_id = $1", TEST_USER_ID)


async def main() -> None:
    await init_db()
    pool = await get_pool()

    existing_settings = await pool.fetchrow("SELECT 1 FROM user_settings WHERE user_id = $1", TEST_USER_ID)
    existing_profile = await pool.fetchrow("SELECT 1 FROM user_fitness_profile WHERE user_id = $1", TEST_USER_ID)
    if existing_settings or existing_profile:
        print(f"СТОП: тестовый user_id {TEST_USER_ID} уже используется в БД")
        await close_pool()
        return

    user = FakeUser(TEST_USER_ID)
    log: list = []
    failures: list = []

    try:
        state = make_state("start")

        # 1) /start, язык ещё не выбран
        msg_start = FakeMessage("/start", user, log)
        await handlers.cmd_start(msg_start, state)

        print("=== Шаг 1: /start (язык не выбран) ===")
        for entry in log:
            print(f"  [{entry['type']}] {entry['text'][:120]!r}")
        if len(log) != 2:
            failures.append(f"Ожидалось 2 сообщения после /start (приветствие + выбор языка), получено {len(log)}")
        else:
            greeting, language_prompt = log[0]["text"], log[1]["text"]
            # Приветствие трёхъязычное (язык ещё не выбран) — проверяем длину КАЖДОЙ строки
            # по отдельности, а не всего блока (который втрое длиннее одноязычного варианта).
            greeting_lines = [line for line in greeting.split("\n") if line.strip()]
            if "LiftMate" not in greeting or len(greeting_lines) != 3 or any(len(line) > 120 for line in greeting_lines):
                failures.append(f"Приветствие выглядит не минимальным: {greeting!r}")
            for forbidden in ["Упражнения", "Лидерборд", "ещё один подход", "one more set", "encore une série", "📋", "🏆"]:
                if forbidden in greeting:
                    failures.append(f"Приветствие всё ещё упоминает кнопки/фичи ({forbidden!r}): {greeting!r}")
            if "выбери" not in language_prompt.lower() and "choose" not in language_prompt.lower():
                failures.append(f"Второе сообщение не похоже на выбор языка: {language_prompt!r}")
        log.clear()

        # 2) выбор языка ru
        callback_msg = FakeMessage("", user, log)
        callback = FakeCallbackQuery(f"{keyboards.LANGUAGE_CALLBACK_PREFIX}:ru", user, callback_msg)
        await handlers.handle_language_selected(callback, state)

        print("\n=== Шаг 2: выбор языка ru -> должен сразу пойти мини-опрос профиля ===")
        for entry in log:
            print(f"  [{entry['type']}] {entry['text'][:150]!r} reply_markup={'да' if entry['reply_markup'] else 'нет'}")
        if len(log) != 2:
            failures.append(f"Ожидалось 2 сообщения после выбора языка (подтверждение + опрос), получено {len(log)}")
        else:
            confirm, survey_start = log[0], log[1]
            if "погнали" in survey_start["text"].lower() or "let's go" in survey_start["text"].lower():
                failures.append(f"Вопрос профиля содержит призыв 'погнали': {survey_start['text']!r}")
            if survey_start["reply_markup"] is None:
                failures.append("К первому вопросу опроса не прикреплена постоянная клавиатура")
            if "стаж" not in survey_start["text"].lower() and "месяц" not in survey_start["text"].lower() and "training" not in survey_start["text"].lower() and "entraîn" not in survey_start["text"].lower():
                failures.append(f"Первый вопрос опроса не похож на вопрос про стаж: {survey_start['text']!r}")
        log.clear()

        current_state = await state.get_state()
        print(f"\nТекущее FSM-состояние после выбора языка: {current_state}")

        # 3) отвечаем на вопрос про стаж (реальный GPT-парсинг через parse_experience_months)
        msg_experience = FakeMessage("2 года", user, log)
        await handlers.handle_profile_experience(msg_experience, state)
        print("\n=== Шаг 3: ответ про стаж -> вопрос про оборудование ===")
        for entry in log:
            print(f"  [{entry['type']}] {entry['text'][:120]!r}")
        log.clear()

        # 4) выбор оборудования кнопкой
        callback_msg2 = FakeMessage("", user, log)
        callback2 = FakeCallbackQuery(f"{keyboards.EQUIPMENT_CALLBACK_PREFIX}:full_gym", user, callback_msg2)
        await handlers.handle_equipment_selected(callback2, state)
        print("\n=== Шаг 4: выбор оборудования -> уточнение текстом ===")
        for entry in log:
            print(f"  [{entry['type']}] {entry['text'][:120]!r}")
        log.clear()

        # 5) уточнение оборудования текстом
        msg_equipment_details = FakeMessage("штанга, гантели, тренажёры", user, log)
        await handlers.handle_profile_equipment_details(msg_equipment_details, state)
        print("\n=== Шаг 5: уточнение оборудования -> вопрос про ограничения ===")
        for entry in log:
            print(f"  [{entry['type']}] {entry['text'][:120]!r}")
        log.clear()

        # 6) "Нет" на вопрос про ограничения -> конец опроса -> должен быть переход в Web App
        callback_msg3 = FakeMessage("", user, log)
        callback3 = FakeCallbackQuery(keyboards.LIMITATIONS_NONE_CALLBACK, user, callback_msg3)
        await handlers.handle_limitations_none(callback3, state)
        print("\n=== Шаг 6: 'Нет' ограничений -> должен быть переход в Web App (НЕ profile_saved_text) ===")
        for entry in log:
            print(f"  [{entry['type']}] {entry['text'][:150]!r} reply_markup={'да' if entry['reply_markup'] else 'нет'}")

        webapp_messages = [e for e in log if e["type"] == "answer"]
        if not webapp_messages:
            failures.append("Не найдено сообщение с переходом в Web App после опроса")
        else:
            final = webapp_messages[-1]
            if "профиль сохранён" in final["text"].lower() or "profile saved" in final["text"].lower():
                failures.append(f"После онбординга показан обычный profile_saved_text вместо перехода в Web App: {final['text']!r}")
            if not has_button_with_webapp(final["reply_markup"]):
                failures.append("К сообщению перехода в Web App не прикреплена inline-кнопка с web_app")
        log.clear()

        # Проверяем состояние БД после опроса
        profile_row = await pool.fetchrow("SELECT * FROM user_fitness_profile WHERE user_id = $1", TEST_USER_ID)
        print(f"\nПрофиль в БД после опроса: {dict(profile_row) if profile_row else None}")
        if profile_row is None:
            failures.append("Профиль не сохранился в БД после онбординга")
        elif profile_row["equipment_type"] != "full_gym":
            failures.append(f"equipment_type сохранён неверно: {profile_row['equipment_type']!r}")

        # 7) первое свободное сообщение после онбординга -> должно показать объяснение трекинга
        msg_workout1 = FakeMessage("жим 80 на 8", user, log)
        await handlers.handle_text_message(msg_workout1, state)
        print("\n=== Шаг 7: первое свободное сообщение после онбординга ===")
        for entry in log:
            print(f"  [{entry['type']}] {entry['text'][:150]!r}")

        if len(log) < 2:
            failures.append(f"Ожидалось минимум 2 сообщения (объяснение трекинга + реакция на сообщение), получено {len(log)}")
        else:
            intro = log[0]["text"]
            if "жим" not in intro.lower() and "bench" not in intro.lower() and "développé" not in intro.lower():
                failures.append(f"Первое сообщение не похоже на объяснение трекинга: {intro!r}")
        first_batch_len = len(log)
        log.clear()

        # 8) второе свободное сообщение -> объяснение трекинга НЕ должно повториться
        msg_workout2 = FakeMessage("присед 100 на 5", user, log)
        await handlers.handle_text_message(msg_workout2, state)
        print("\n=== Шаг 8: второе свободное сообщение -> объяснение НЕ должно повториться ===")
        for entry in log:
            print(f"  [{entry['type']}] {entry['text'][:150]!r}")

        for entry in log:
            if "жим 80" in entry["text"] or "bench 80" in entry["text"] or "développé 80" in entry["text"]:
                failures.append(f"Объяснение трекинга показалось повторно на втором сообщении: {entry['text']!r}")
        log.clear()

        tracking_flag = await pool.fetchval("SELECT tracking_intro_shown FROM user_settings WHERE user_id = $1", TEST_USER_ID)
        print(f"\ntracking_intro_shown в БД: {tracking_flag} (ожидаем True)")
        if not tracking_flag:
            failures.append("tracking_intro_shown не выставился в true после первого сообщения")

    finally:
        await cleanup(pool)
        verify_settings = await pool.fetchrow("SELECT 1 FROM user_settings WHERE user_id = $1", TEST_USER_ID)
        verify_profile = await pool.fetchrow("SELECT 1 FROM user_fitness_profile WHERE user_id = $1", TEST_USER_ID)
        print(f"\nПосле cleanup: user_settings={'осталось' if verify_settings else 'чисто'}, "
              f"user_fitness_profile={'осталось' if verify_profile else 'чисто'}")
        await close_pool()

    print("\n" + "=" * 70)
    if failures:
        print(f"НАЙДЕНО ПРОБЛЕМ: {len(failures)}")
        for f in failures:
            print(f"  !!! {f}")
    else:
        print("OK — все проверки прошли успешно, новая последовательность онбординга работает как задумано.")


if __name__ == "__main__":
    asyncio.run(main())
