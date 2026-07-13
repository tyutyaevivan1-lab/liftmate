"""Обработчики сообщений и inline-кнопок Telegram-бота LiftMate."""

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import history
import keyboards
from config import DATABASE_URL, WEBAPP_URL
from ai_parser import (
    generate_clarifying_question,
    generate_friendly_reply,
    generate_unclear_reply,
    generate_update_confirmation_reply,
    get_missing_fields,
    not_understood_message,
    parse_clarification_reply,
    parse_workout_message,
)
from database import (
    add_custom_exercise,
    add_workout,
    count_all_workouts,
    count_user_workouts,
    get_custom_exercise_by_id,
    get_custom_exercises,
    get_last_workout,
    get_last_workout_for_user,
    get_leaderboard_top,
    get_recent_workouts,
    get_user_language,
    get_user_rank,
    redact_database_url,
    set_user_language,
    update_streak_on_workout,
    update_workout_by_id,
)
from exercises_data import find_exercise, get_canonical_exercise_name, get_exercise_display_name
from leaderboard import build_leaderboard_message
from states import WorkoutStates

router = Router()


def _telegram_language(user) -> str:
    """Язык из настроек клиента Telegram — запасной вариант, пока пользователь ещё не выбрал язык явно."""
    return getattr(user, "language_code", None) or "en"


async def _get_language(user_id: int, telegram_user) -> str:
    """
    Возвращает язык интерфейса пользователя: явно выбранный через /language (хранится в БД),
    а если ещё не выбран — язык из настроек Telegram-клиента как временный запасной вариант.
    Это единственный источник языка ответа — сообщения GPT-парсеру больше не анализируются
    на предмет языка, распознавание данных о тренировке работает независимо от языка ввода.
    """
    stored = await get_user_language(user_id)
    return stored or _telegram_language(telegram_user)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    """
    Обработчик команды /start. Если язык интерфейса ещё не выбран — сначала просим выбрать
    язык, а обычное приветствие показываем сразу после выбора. Если язык уже известен —
    сразу показываем приветствие на этом языке.
    """
    await state.clear()
    user_id = message.from_user.id
    language = await get_user_language(user_id)

    if language is None:
        await state.update_data(show_welcome_after_language=True)
        await message.answer(
            keyboards.choose_language_text(),
            reply_markup=keyboards.build_language_keyboard(),
        )
        return

    await message.answer(
        keyboards.welcome_text(language),
        reply_markup=keyboards.build_main_reply_keyboard(language),
    )


@router.message(Command("language"))
async def cmd_language(message: Message, state: FSMContext) -> None:
    """Команда /language — доступна в любой момент, чтобы выбрать или сменить язык интерфейса."""
    await state.clear()
    await message.answer(
        keyboards.choose_language_text(),
        reply_markup=keyboards.build_language_keyboard(),
    )


@router.callback_query(F.data.startswith(f"{keyboards.LANGUAGE_CALLBACK_PREFIX}:"))
async def handle_language_selected(callback: CallbackQuery, state: FSMContext) -> None:
    """Пользователь выбрал язык интерфейса — сохраняем его в БД и подтверждаем выбор."""
    language = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id

    await set_user_language(user_id, language)

    await callback.message.edit_text(keyboards.language_confirmed_text(language))
    await callback.answer()

    # Постоянная клавиатура внизу экрана обновляется отдельным сообщением — Telegram
    # не позволяет прикрепить ReplyKeyboardMarkup через edit_text, только через новое sendMessage
    data = await state.get_data()
    if data.get("show_welcome_after_language"):
        # Язык выбирался в рамках самого первого /start — сразу показываем приветствие
        await state.clear()
        await callback.message.answer(
            keyboards.welcome_text(language),
            reply_markup=keyboards.build_main_reply_keyboard(language),
        )
    else:
        # Обычная смена языка — просто обновляем подписи на клавиатуре внизу
        await callback.message.answer(
            keyboards.keyboard_hint_text(language),
            reply_markup=keyboards.build_main_reply_keyboard(language),
        )


@router.message(Command("exercises"))
async def cmd_exercises(message: Message, state: FSMContext) -> None:
    """
    Команда /exercises — показывает inline-клавиатуру с категориями упражнений,
    а также кнопку, открывающую полноценный Web App с тем же меню.
    """
    await state.clear()
    user_id = message.from_user.id
    language = await _get_language(user_id, message.from_user)

    await message.answer(
        keyboards.choose_category_text(language),
        reply_markup=keyboards.build_categories_keyboard(language, WEBAPP_URL),
    )


@router.message(Command("leaderboard"))
async def cmd_leaderboard(message: Message, state: FSMContext) -> None:
    """Команда /leaderboard — глобальный топ-10 по серии тренировок + место пользователя."""
    await state.clear()
    user_id = message.from_user.id
    language = await _get_language(user_id, message.from_user)

    top_entries = await get_leaderboard_top(10)
    user_rank_info = await get_user_rank(user_id)

    text = build_leaderboard_message(top_entries, user_rank_info, language)
    await message.answer(text)


@router.message(Command("debug_db"))
async def cmd_debug_db(message: Message, state: FSMContext) -> None:
    """
    ВРЕМЕННАЯ диагностическая команда — убрать после того, как разберёмся, почему
    записи тренировок не долетают до PostgreSQL (см. add_workout в database.py).

    Показывает: к какому DATABASE_URL реально подключён этот процесс (пароль скрыт),
    сколько всего строк в workouts (все пользователи), сколько из них — у текущего
    пользователя, и последние 5 его записей с EXERCISE_NAME В КАВЫЧКАХ (repr) КАК ОН
    ЕСТЬ в базе — чтобы визуально увидеть лишний пробел или отличие в регистре, из-за
    которого поиск по конкретному названию может не находить уже сохранённые записи.
    """
    await state.clear()
    user_id = message.from_user.id

    total = await count_all_workouts()
    mine = await count_user_workouts(user_id)
    recent = await get_recent_workouts(user_id, limit=5)

    lines = [
        "🔧 Debug DB",
        f"Подключение: {redact_database_url(DATABASE_URL)}",
        f"Всего записей в workouts (все пользователи): {total}",
        f"Твоих записей (user_id={user_id}): {mine}",
        "",
        "Последние 5 твоих записей (exercise_name как в базе, в repr — видны лишние пробелы/регистр):",
    ]

    if recent:
        for row in recent:
            date_str = row["created_at"].split("T")[0]
            lines.append(
                f"{row['exercise_name']!r} — {row['weight']}кг × {row['reps']}, {row['sets']} подх. ({date_str})"
            )
    else:
        lines.append("(записей ещё нет)")

    await message.answer("\n".join(lines))


@router.message(F.text.in_(keyboards.ALL_REPLY_BUTTON_TEXTS))
async def handle_reply_keyboard_button(message: Message, state: FSMContext) -> None:
    """
    Нажатие кнопки постоянной клавиатуры внизу экрана — алиас соответствующей команды.
    Зарегистрирован раньше состояний FSM и общего текстового обработчика, поэтому кнопка
    работает всегда, даже если бот в этот момент ждал уточнения по текущей записи
    (как и сами команды /exercises, /leaderboard, /language).
    """
    action = keyboards.match_reply_button(message.text)

    if action == "exercises":
        await cmd_exercises(message, state)
    elif action == "leaderboard":
        await cmd_leaderboard(message, state)
    elif action == "language":
        await cmd_language(message, state)


async def _reply(message: Message, user_id: int, text: str) -> None:
    """Отправляет ответ пользователю и сохраняет его в историю переписки для контекста GPT."""
    history.add_message(user_id, "bot", text)
    await message.answer(text)


async def _save_and_reply(message: Message, user_id: int, data: dict) -> None:
    """Сохраняет новую запись о тренировке в БД и отвечает пользователю с учётом прогресса."""
    exercise_name = data["exercise_name"]
    weight = data["weight"]
    reps = data["reps"]
    sets = data["sets"]
    language = data["language"]

    # Ищем предыдущую запись этого же упражнения ДО того, как сохраним новую
    previous = await get_last_workout(user_id, exercise_name)
    await add_workout(user_id, exercise_name, weight, reps, sets)
    # Серия дней считается по факту записи НОВОЙ тренировки (а не правки уже существующей,
    # см. _update_and_reply) — один раз за вызов, независимо от того, сколько упражнений
    # пользователь запишет в этот же день
    await update_streak_on_workout(user_id)
    previous_weight = previous["weight"] if previous else None
    previous_reps = previous["reps"] if previous else None

    reply = await generate_friendly_reply(
        exercise_name=exercise_name,
        weight=weight,
        reps=reps,
        sets=sets,
        language=language,
        previous_weight=previous_weight,
        previous_reps=previous_reps,
    )
    await _reply(message, user_id, reply)


async def _update_and_reply(message: Message, user_id: int, data: dict) -> None:
    """Обновляет уже существующую запись (например, после «ещё один подход») и подтверждает."""
    await update_workout_by_id(data["workout_id"], data["weight"], data["reps"], data["sets"])

    reply = await generate_update_confirmation_reply(
        exercise_name=data["exercise_name"],
        weight=data["weight"],
        reps=data["reps"],
        sets=data["sets"],
        language=data["language"],
    )
    await _reply(message, user_id, reply)


async def _resolve_workout(message: Message, user_id: int, state: FSMContext, parsed: dict) -> None:
    """
    Если в parsed не хватает веса/повторений/подходов — переходит в состояние ожидания
    и вежливо просит уточнить недостающее. Если данных достаточно — сохраняет либо
    обновляет запись (в зависимости от parsed["is_update"]). Ответ всегда на языке
    parsed["language"] — явно выбранном пользователем языке интерфейса.
    """
    missing = get_missing_fields(parsed)

    if missing:
        await state.set_state(WorkoutStates.waiting_for_details)
        await state.update_data(pending=parsed, missing=missing)

        question = await generate_clarifying_question(
            exercise_name=parsed["exercise_name"],
            known=parsed,
            missing=missing,
            language=parsed["language"],
        )
        await _reply(message, user_id, question)
        return

    await state.clear()

    if parsed.get("is_update"):
        await _update_and_reply(message, user_id, parsed)
    else:
        await _save_and_reply(message, user_id, parsed)


async def _start_exercise_flow(message: Message, user_id: int, state: FSMContext, exercise_name: str, language: str) -> None:
    """
    Общая точка входа для упражнения, выбранного через меню (встроенное или своё):
    показывает последний результат (если есть) и запускает обычный FSM-диалог для
    сбора веса/повторений/подходов — так же, как при свободном текстовом вводе.
    """
    last = await get_last_workout(user_id, exercise_name)
    if last is not None:
        await _reply(message, user_id, keyboards.format_last_result(last, language))

    parsed = {
        "action": "new_entry",
        "language": language,
        "exercise_name": exercise_name,
        "weight": None,
        "reps": None,
        "sets": None,
        "is_update": False,
    }
    await _resolve_workout(message, user_id, state, parsed)


@router.callback_query(F.data.startswith(f"{keyboards.CATEGORY_CALLBACK_PREFIX}:"))
async def handle_category_selected(callback: CallbackQuery, state: FSMContext) -> None:
    """Пользователь выбрал категорию — показываем список упражнений этой категории."""
    category_key = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id
    language = await _get_language(user_id, callback.from_user)

    custom_exercises = await get_custom_exercises(user_id, category_key)

    await callback.message.edit_text(
        keyboards.choose_exercise_text(category_key, language),
        reply_markup=keyboards.build_exercises_keyboard(category_key, language, custom_exercises),
    )
    await callback.answer()


@router.callback_query(F.data == keyboards.BACK_TO_CATEGORIES_CALLBACK)
async def handle_back_to_categories(callback: CallbackQuery, state: FSMContext) -> None:
    """Кнопка "Назад к категориям" — возвращает клавиатуру верхнего уровня."""
    await state.clear()
    user_id = callback.from_user.id
    language = await _get_language(user_id, callback.from_user)

    await callback.message.edit_text(
        keyboards.choose_category_text(language),
        reply_markup=keyboards.build_categories_keyboard(language, WEBAPP_URL),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(f"{keyboards.ADD_CUSTOM_CALLBACK_PREFIX}:"))
async def handle_add_custom_exercise(callback: CallbackQuery, state: FSMContext) -> None:
    """Кнопка "Добавить своё упражнение" — просим написать название текстом."""
    category_key = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id
    language = await _get_language(user_id, callback.from_user)

    await state.set_state(WorkoutStates.waiting_for_custom_name)
    await state.update_data(custom_category=category_key, language=language)

    await callback.message.edit_text(keyboards.ask_custom_name_text(language))
    await callback.answer()


@router.callback_query(F.data.startswith(f"{keyboards.EXERCISE_CALLBACK_PREFIX}:"))
async def handle_exercise_selected(callback: CallbackQuery, state: FSMContext) -> None:
    """Пользователь выбрал конкретное встроенное упражнение из меню."""
    _, category_key, exercise_key = callback.data.split(":", 2)
    user_id = callback.from_user.id
    language = await _get_language(user_id, callback.from_user)

    exercise = find_exercise(category_key, exercise_key)
    exercise_name = get_canonical_exercise_name(exercise)
    display_name = get_exercise_display_name(exercise, language)

    await callback.message.edit_text(f"✅ {display_name}")
    await callback.answer()

    await _start_exercise_flow(callback.message, user_id, state, exercise_name, language)


@router.callback_query(F.data.startswith(f"{keyboards.CUSTOM_EXERCISE_CALLBACK_PREFIX}:"))
async def handle_custom_exercise_selected(callback: CallbackQuery, state: FSMContext) -> None:
    """Пользователь выбрал ранее добавленное своё упражнение из меню."""
    custom_id = int(callback.data.split(":", 1)[1])
    user_id = callback.from_user.id
    language = await _get_language(user_id, callback.from_user)

    custom = await get_custom_exercise_by_id(custom_id)
    if custom is None or custom["user_id"] != user_id:
        await callback.answer()
        return

    exercise_name = custom["exercise_name"]

    await callback.message.edit_text(f"✅ {exercise_name.capitalize()}")
    await callback.answer()

    await _start_exercise_flow(callback.message, user_id, state, exercise_name, language)


@router.message(WorkoutStates.waiting_for_custom_name)
async def handle_custom_exercise_name(message: Message, state: FSMContext) -> None:
    """Пользователь написал название своего упражнения после нажатия соответствующей кнопки."""
    data = await state.get_data()
    category_key = data.get("custom_category")
    language = data.get("language", "en")
    user_id = message.from_user.id

    exercise_name = message.text.strip().lower()
    await add_custom_exercise(user_id, exercise_name, category_key)
    history.add_message(user_id, "user", message.text)

    await state.clear()
    await _start_exercise_flow(message, user_id, state, exercise_name, language)


async def _process_new_message(message: Message, user_id: int, state: FSMContext, text: str, language: str) -> None:
    """
    Разбирает новое сообщение пользователя (не являющееся ответом на уточняющий вопрос):
    определяет, новый ли это подход, дополнение к последнему обсуждаемому упражнению,
    что-то неоднозначное, или сообщение вообще не о тренировке. Извлечение данных
    (упражнение/вес/повторения/подходы) работает независимо от языка текста — но отвечает
    бот всегда на языке из user_settings, переданном в параметре language.
    """
    # Контекст для GPT: последние реплики переписки + последняя сохранённая запись
    context = history.get_history(user_id)
    last_saved = await get_last_workout_for_user(user_id)

    parsed = await parse_workout_message(text, history=context, last_saved=last_saved)
    history.add_message(user_id, "user", text)

    if parsed is None:
        await _reply(message, user_id, not_understood_message(language))
        return

    action = parsed.get("action")

    # Подстраховка: если GPT решил, что это обновление, а обновлять нечего — считаем неоднозначным
    if action == "update_last" and last_saved is None:
        action = "unclear"

    if action == "not_workout":
        await _reply(message, user_id, not_understood_message(language))
        return

    if action == "unclear":
        reply = await generate_unclear_reply(language=language, text=text)
        await _reply(message, user_id, reply)
        return

    parsed["language"] = language

    if action == "update_last":
        # Название упражнения и недостающие поля берём из последней сохранённой записи,
        # а не из ответа GPT — так надёжнее, чем полагаться на точное совпадение строк
        parsed["exercise_name"] = last_saved["exercise_name"]
        for field in ("weight", "reps", "sets"):
            if parsed.get(field) is None:
                parsed[field] = last_saved[field]
        parsed["is_update"] = True
        parsed["workout_id"] = last_saved["id"]
    else:
        parsed["is_update"] = False

    await _resolve_workout(message, user_id, state, parsed)


@router.message(WorkoutStates.waiting_for_details)
async def handle_clarification_reply(message: Message, state: FSMContext) -> None:
    """
    Обрабатывает ответ пользователя, когда бот ждёт уточнения недостающих данных
    (веса, повторений или количества подходов) для незавершённой записи.
    """
    user_id = message.from_user.id
    # Берём язык заново (а не из pending) — на случай, если пользователь сменил его
    # командой /language прямо посреди уточняющего диалога
    language = await _get_language(user_id, message.from_user)

    data = await state.get_data()
    pending = data.get("pending", {})
    missing = data.get("missing", [])

    result = await parse_clarification_reply(
        pending=pending,
        missing=missing,
        language=language,
        text=message.text,
    )
    action = result.get("action")

    # Пользователь вместо ответа описал новое (или обновляющее) сообщение —
    # разбираем его с нуля, не зависая в старом ожидании
    if action == "new_workout":
        await state.clear()
        await _process_new_message(message, user_id, state, message.text, language)
        return

    history.add_message(user_id, "user", message.text)

    # Сообщение не по теме — выходим из ожидания, а не зависаем в нём навсегда
    if action == "irrelevant":
        await state.clear()
        await _reply(message, user_id, not_understood_message(language))
        return

    # action == "fill": дополняем уже известные данные ответом пользователя (и актуализируем язык)
    pending["language"] = language
    for field in ("weight", "reps", "sets"):
        value = result.get(field)
        if value is not None:
            pending[field] = value

    await _resolve_workout(message, user_id, state, pending)


@router.message(F.text)
async def handle_text_message(message: Message, state: FSMContext) -> None:
    """Обрабатывает произвольный текст, когда бот не ждёт уточнения (обычный вход)."""
    user_id = message.from_user.id
    language = await _get_language(user_id, message.from_user)
    await _process_new_message(message, user_id, state, message.text, language)
