"""Обработчики сообщений и inline-кнопок Telegram-бота LiftMate."""

import json
from typing import Optional

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
    get_fitness_profile,
    get_last_user_program,
    get_last_workout,
    get_last_workout_for_user,
    get_leaderboard_top,
    get_recent_workouts,
    get_user_language,
    get_user_rank,
    get_user_stats,
    redact_database_url,
    save_fitness_profile,
    save_user_program,
    set_user_language,
    update_split_preference,
    update_streak_on_workout,
    update_workout_by_id,
)
from exercises_data import find_exercise, get_canonical_exercise_name, get_exercise_display_name
from leaderboard import build_leaderboard_message
from fitness_profile import parse_experience_months
from program import (
    FREQUENCY_TO_DAYS_PER_WEEK,
    generate_split_program,
    generate_workout_program,
    get_split_options,
    publish_program,
    split_label,
)
from states import ProfileStates, ProgramStates, WorkoutStates

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


async def _ask_program_source(message: Message, state: FSMContext, language: str) -> None:
    """Обычный первый вопрос /program (способ составления) — когда профиль уже есть."""
    await state.set_state(ProgramStates.awaiting_choice)
    await message.answer(
        keyboards.ask_program_source_text(language),
        reply_markup=keyboards.build_program_source_keyboard(language),
    )


async def _start_profile_survey(message: Message, state: FSMContext, *, continue_to_program: bool, language: str) -> None:
    """
    Запускает мини-опрос профиля (опыт/оборудование/ограничения) — используется и при
    первом заходе в /program (профиля ещё нет), и по явному /update_profile.
    continue_to_program сохраняется в FSM-данных и решает, что делать по окончании опроса:
    сразу перейти к обычному диалогу /program, либо просто подтвердить сохранение профиля.
    """
    await state.set_state(ProfileStates.waiting_for_experience)
    await state.update_data(continue_to_program=continue_to_program)
    await message.answer(keyboards.ask_experience_text(language))


@router.message(Command("program"))
async def cmd_program(message: Message, state: FSMContext) -> None:
    """
    Команда /program — если профиль пользователя ещё не заполнен, сначала запускает
    короткий мини-опрос (опыт/оборудование/ограничения, см. states.ProfileStates),
    иначе сразу переходит к обычному вопросу о способе составления программы.
    """
    await state.clear()
    user_id = message.from_user.id
    language = await _get_language(user_id, message.from_user)

    profile = await get_fitness_profile(user_id)
    if profile is None:
        await _start_profile_survey(message, state, continue_to_program=True, language=language)
        return

    await _ask_program_source(message, state, language)


@router.message(Command("update_profile"))
async def cmd_update_profile(message: Message, state: FSMContext) -> None:
    """Команда /update_profile — заново проходит мини-опрос профиля и перезаписывает сохранённые данные."""
    await state.clear()
    user_id = message.from_user.id
    language = await _get_language(user_id, message.from_user)

    await _start_profile_survey(message, state, continue_to_program=False, language=language)


@router.callback_query(F.data.startswith(f"{keyboards.EQUIPMENT_CALLBACK_PREFIX}:"))
async def handle_equipment_selected(callback: CallbackQuery, state: FSMContext) -> None:
    """Вопрос 2: пользователь выбрал тип оборудования кнопкой — просим необязательное уточнение текстом."""
    equipment_type = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id
    language = await _get_language(user_id, callback.from_user)

    await state.update_data(equipment_type=equipment_type)
    await state.set_state(ProfileStates.waiting_for_equipment_details)

    await callback.message.edit_text(f"✅ {keyboards.equipment_label(equipment_type, language)}")
    await callback.answer()
    await callback.message.answer(keyboards.ask_equipment_details_text(language))


async def _ask_limitations(message: Message, state: FSMContext, language: str) -> None:
    """Вопрос 3: травмы/ограничения — свободный текст либо кнопка "Нет"."""
    await state.set_state(ProfileStates.waiting_for_limitations)
    await message.answer(
        keyboards.ask_limitations_text(language),
        reply_markup=keyboards.build_limitations_keyboard(language),
    )


async def _finish_profile_survey(
    message: Message,
    state: FSMContext,
    user_id: int,
    language: str,
    limitations: Optional[str],
) -> None:
    """
    Сохраняет базовый профиль (стаж/оборудование/ограничения) и либо продолжает в обычный
    диалог /program, либо (если это /update_profile и пользователь уже когда-то выбирал
    сплит) переспрашивает частоту/сплит, либо просто подтверждает сохранение.
    """
    data = await state.get_data()
    continue_to_program = data.get("continue_to_program", False)

    existing_profile = await get_fitness_profile(user_id)
    had_split_before = bool(existing_profile and existing_profile.get("days_per_week") is not None)

    await save_fitness_profile(
        user_id,
        data.get("experience_months"),
        data.get("equipment_type"),
        data.get("equipment_details"),
        limitations,
    )
    await state.clear()

    profile_saved_message = keyboards.profile_saved_text(language)
    if not continue_to_program and not had_split_before:
        # /update_profile у пользователя, который ни разу не заходил в "Сплит на неделю"
        # (в т.ч. legacy-профиль с days_per_week ещё NULL) — рассказываем о фиче разово.
        # "Разово" здесь = показывается при КАЖДОМ /update_profile, пока days_per_week не
        # заполнится через /program — как только пользователь пройдёт вопрос про частоту
        # хотя бы раз, had_split_before станет True и подсказка больше не появится.
        profile_saved_message += "\n\n" + keyboards.split_feature_hint_text(language)
    await message.answer(profile_saved_message)

    if continue_to_program:
        await _ask_program_source(message, state, language)
    elif had_split_before:
        # /update_profile: сплит уже когда-то выбирался — предлагаем обновить и его тоже
        await _start_split_flow(message, state, user_id, language, for_program=False, force_ask_frequency=True)


@router.callback_query(F.data == keyboards.LIMITATIONS_NONE_CALLBACK)
async def handle_limitations_none(callback: CallbackQuery, state: FSMContext) -> None:
    """Вопрос 3, кнопка "Нет" — ограничений нет."""
    user_id = callback.from_user.id
    language = await _get_language(user_id, callback.from_user)

    await callback.message.edit_text(f"✅ {keyboards.limitations_none_label(language)}")
    await callback.answer()
    await _finish_profile_survey(callback.message, state, user_id, language, limitations=None)


@router.message(Command("my_program"))
async def cmd_my_program(message: Message, state: FSMContext) -> None:
    """
    Команда /my_program — показывает последнюю сохранённую программу тренировки. Публикуем
    заново через Telegraph (а не просто пересылаем сохранённый program_text напрямую) —
    для многодневного сплита сохранённый текст может превышать лимит Telegram в 4096
    символов, и send_message с ним точно так же упал бы, как и при самой генерации.
    """
    await state.clear()
    user_id = message.from_user.id
    language = await _get_language(user_id, message.from_user)

    saved = await get_last_user_program(user_id)
    if saved is None:
        await message.answer(keyboards.no_saved_program_text(language))
        return

    if not saved.get("program_data"):
        # Старая запись без структурированных данных (до появления program_data) —
        # ничего другого не остаётся, кроме как прислать как есть
        await message.answer(saved["program_text"])
        return

    days = json.loads(saved["program_data"])["days"]
    await publish_program(message.answer, days, language, message.from_user.full_name)


async def _generate_and_send_program(
    message: Message,
    user_id: int,
    *,
    mode: str,
    language: str,
    user_display_name: str,
    goal: Optional[str] = None,
) -> None:
    """
    Генерирует программу тренировки (один день — "по цели"/"история") через GPT,
    публикует её пользователю (см. program.publish_program) и сохраняет для /my_program
    и Web App. Список упражнений оборачивается в {"days": [...]} — тот же формат
    хранения, что и у многодневного "Сплита на неделю" (см. _generate_and_send_split_program),
    с единственным днём без названия (day_title=None) — так Web App работает с ОДНОЙ
    структурой независимо от того, сколько дней в программе.

    user_display_name передаётся явно, а не берётся из message.from_user — здесь message
    это callback.message (сообщение БОТА), а не сообщение пользователя.
    """
    result = await generate_workout_program(user_id, mode, language, goal=goal)
    days = [{"day_title": None, "exercises": result["exercises"]}]
    program_data = json.dumps({"days": days}, ensure_ascii=False)
    await save_user_program(user_id, result["text"], program_data)
    await publish_program(message.answer, days, language, user_display_name)


# ---------------------------------------------------------------------------
# "Сплит на неделю" — третий способ составления программы (см. handle_program_source_selected
# ниже). Частота тренировок в неделю (fitness_profile.days_per_week) и сплит
# (fitness_profile.chosen_split) спрашиваются лениво при первом выборе этой ветки и
# сохраняются для будущих генераций; реальный выбор сплита (когда есть из чего выбирать)
# доступен только premium — free видит варианты, но зафиксирован на первом (см.
# program.get_split_options).
# ---------------------------------------------------------------------------


async def _start_split_flow(
    message: Message,
    state: FSMContext,
    user_id: int,
    language: str,
    *,
    for_program: bool,
    force_ask_frequency: bool = False,
) -> None:
    """
    Точка входа в сплит-флоу. for_program=True — обычный /program (после определения
    сплита сразу спрашиваем цель и генерируем); for_program=False — вызвано из
    /update_profile (после обновления сплита просто подтверждаем и останавливаемся).
    force_ask_frequency=True заставляет переспросить частоту, даже если она уже
    сохранена (используется именно в ветке /update_profile).
    """
    await state.update_data(split_for_program=for_program)

    profile = await get_fitness_profile(user_id)
    days_per_week = None if force_ask_frequency else (profile.get("days_per_week") if profile else None)

    if days_per_week is None:
        await state.set_state(ProgramStates.awaiting_frequency)
        await message.answer(
            keyboards.ask_frequency_text(language),
            reply_markup=keyboards.build_frequency_keyboard(language),
        )
        return

    await _resolve_split_choice(message, state, user_id, language, days_per_week)


async def _resolve_split_choice(
    message: Message,
    state: FSMContext,
    user_id: int,
    language: str,
    days_per_week: int,
) -> None:
    """
    По частоте + стажу + premium-статусу определяет доступные варианты сплита
    (см. program.get_split_options) и либо сразу фиксирует сплит (нет выбора), либо
    показывает locked-апселл (free, но выбор в принципе есть), либо реальные кнопки
    выбора (premium).
    """
    await state.update_data(pending_days_per_week=days_per_week)

    profile = await get_fitness_profile(user_id)
    experience_months = profile.get("experience_months") if profile else None
    stats = await get_user_stats(user_id)
    is_premium = bool(stats["is_premium"]) if stats else False

    result = get_split_options(days_per_week, experience_months, is_premium)

    if not result["choice_shown"]:
        await update_split_preference(user_id, days_per_week, result["fixed"])
        await _after_split_resolved(message, state, language)
        return

    if result["locked"]:
        await state.update_data(pending_fixed_split=result["fixed"])
        await message.answer(
            keyboards.split_locked_message(result["options"], result["fixed"], language),
            reply_markup=keyboards.build_split_locked_keyboard(result["fixed"], language),
        )
        return

    # premium — реальный выбор из нескольких вариантов
    await message.answer(
        keyboards.ask_split_choice_text(language),
        reply_markup=keyboards.build_split_choice_keyboard(result["options"], language),
    )


async def _after_split_resolved(message: Message, state: FSMContext, language: str) -> None:
    """
    После того как chosen_split определён и сохранён в профиле: если это был обычный
    /program (split_for_program=True) — сразу спрашиваем цель и дальше генерируем;
    если /update_profile (False) — просто подтверждаем и останавливаемся.
    """
    data = await state.get_data()
    if data.get("split_for_program", True):
        await state.set_state(ProgramStates.awaiting_split_goal)
        await message.answer(
            keyboards.ask_split_goal_text(language),
            reply_markup=keyboards.build_split_goal_keyboard(language),
        )
        return

    await state.clear()
    await message.answer(keyboards.profile_saved_text(language))


@router.callback_query(F.data.startswith(f"{keyboards.FREQUENCY_CALLBACK_PREFIX}:"))
async def handle_frequency_selected(callback: CallbackQuery, state: FSMContext) -> None:
    """Пользователь выбрал частоту тренировок в неделю — определяем доступные варианты сплита."""
    freq_key = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id
    language = await _get_language(user_id, callback.from_user)
    days_per_week = FREQUENCY_TO_DAYS_PER_WEEK[freq_key]

    await callback.message.edit_text(f"✅ {keyboards.frequency_label(freq_key, language)}")
    await callback.answer()

    await _resolve_split_choice(callback.message, state, user_id, language, days_per_week)


@router.callback_query(F.data == keyboards.SPLIT_CONTINUE_LOCKED_CALLBACK)
async def handle_split_continue_locked(callback: CallbackQuery, state: FSMContext) -> None:
    """Free-пользователь нажал "Продолжить с {фиксированный сплит}" на апселл-сообщении."""
    user_id = callback.from_user.id
    language = await _get_language(user_id, callback.from_user)
    data = await state.get_data()
    fixed_split = data.get("pending_fixed_split")

    await update_split_preference(user_id, data.get("pending_days_per_week"), fixed_split)

    await callback.message.edit_text(f"✅ {split_label(fixed_split, language)}")
    await callback.answer()
    await _after_split_resolved(callback.message, state, language)


@router.callback_query(F.data == keyboards.SPLIT_LEARN_PREMIUM_CALLBACK)
async def handle_split_learn_premium(callback: CallbackQuery, state: FSMContext) -> None:
    """Free-пользователь нажал "Узнать про Premium" — показываем заглушку и всё равно продолжаем на free."""
    user_id = callback.from_user.id
    language = await _get_language(user_id, callback.from_user)
    data = await state.get_data()

    await callback.answer()
    await callback.message.answer(keyboards.split_premium_info_text(language))

    await update_split_preference(user_id, data.get("pending_days_per_week"), data.get("pending_fixed_split"))
    await _after_split_resolved(callback.message, state, language)


@router.callback_query(F.data.startswith(f"{keyboards.SPLIT_CHOICE_CALLBACK_PREFIX}:"))
async def handle_split_choice_selected(callback: CallbackQuery, state: FSMContext) -> None:
    """Premium-пользователь выбрал конкретный сплит из реального списка вариантов."""
    chosen_split = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id
    language = await _get_language(user_id, callback.from_user)
    data = await state.get_data()

    await update_split_preference(user_id, data.get("pending_days_per_week"), chosen_split)

    await callback.message.edit_text(f"✅ {split_label(chosen_split, language)}")
    await callback.answer()
    await _after_split_resolved(callback.message, state, language)


@router.callback_query(F.data.startswith(f"{keyboards.SPLIT_GOAL_CALLBACK_PREFIX}:"))
async def handle_split_goal_selected(callback: CallbackQuery, state: FSMContext) -> None:
    """Цель для сплит-программы выбрана — генерируем и отправляем недельную программу."""
    goal = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id
    language = await _get_language(user_id, callback.from_user)

    await callback.message.edit_text(f"✅ {keyboards.split_goal_label(goal, language)}")
    await callback.answer()

    await state.clear()
    await _generate_and_send_split_program(callback.message, user_id, goal, language, callback.from_user.full_name)


async def _generate_and_send_split_program(
    message: Message, user_id: int, goal: str, language: str, user_display_name: str
) -> None:
    """
    Генерирует недельную программу по сохранённому в профиле сплиту, публикует (см.
    program.publish_program) и сохраняет. user_display_name передаётся явно, а не берётся
    из message.from_user — здесь message это callback.message (сообщение БОТА), а не
    сообщение пользователя, и message.from_user был бы самим ботом.
    """
    profile = await get_fitness_profile(user_id)
    chosen_split = (profile or {}).get("chosen_split") or "full_body"

    result = await generate_split_program(user_id, chosen_split, goal, language)
    program_data = json.dumps({"days": result["days"]}, ensure_ascii=False)
    await save_user_program(user_id, result["text"], program_data)
    await publish_program(message.answer, result["days"], language, user_display_name)


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
    elif action == "program":
        await cmd_program(message, state)
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


@router.callback_query(F.data.startswith(f"{keyboards.PROGRAM_SOURCE_CALLBACK_PREFIX}:"))
async def handle_program_source_selected(callback: CallbackQuery, state: FSMContext) -> None:
    """Пользователь выбрал способ составления программы: "по цели", "на основе истории" или "сплит на неделю"."""
    source = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id
    language = await _get_language(user_id, callback.from_user)

    await callback.message.edit_text(f"✅ {keyboards.program_source_label(source, language)}")
    await callback.answer()

    if source == "goal":
        await callback.message.answer(
            keyboards.ask_program_goal_text(language),
            reply_markup=keyboards.build_program_goal_keyboard(language),
        )
        return

    if source == "split":
        await _start_split_flow(callback.message, state, user_id, language, for_program=True)
        return

    # source == "history" — сразу генерируем и отправляем программу, доп. вопросов не нужно
    await state.clear()
    await _generate_and_send_program(
        callback.message, user_id, mode="history", language=language, user_display_name=callback.from_user.full_name
    )


@router.callback_query(F.data.startswith(f"{keyboards.PROGRAM_GOAL_CALLBACK_PREFIX}:"))
async def handle_program_goal_selected(callback: CallbackQuery, state: FSMContext) -> None:
    """Пользователь выбрал конкретную цель после "по цели" — генерируем и отправляем программу."""
    goal = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id
    language = await _get_language(user_id, callback.from_user)

    await callback.message.edit_text(f"✅ {keyboards.program_goal_label(goal, language)}")
    await callback.answer()

    await state.clear()
    await _generate_and_send_program(
        callback.message, user_id, mode="goal", language=language, goal=goal, user_display_name=callback.from_user.full_name
    )


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


@router.message(ProfileStates.waiting_for_experience)
async def handle_profile_experience(message: Message, state: FSMContext) -> None:
    """Вопрос 1: свободный текст про стаж тренировок — разбирается через GPT в число месяцев."""
    user_id = message.from_user.id
    language = await _get_language(user_id, message.from_user)

    experience_months = await parse_experience_months(message.text)
    await state.update_data(experience_months=experience_months)
    await state.set_state(None)  # текстовый ответ обработан, дальше — выбор оборудования кнопкой

    await message.answer(
        keyboards.ask_equipment_text(language),
        reply_markup=keyboards.build_equipment_keyboard(language),
    )


@router.message(ProfileStates.waiting_for_equipment_details)
async def handle_profile_equipment_details(message: Message, state: FSMContext) -> None:
    """Необязательное уточнение оборудования текстом, либо /skip — в обоих случаях идём к вопросу 3."""
    user_id = message.from_user.id
    language = await _get_language(user_id, message.from_user)

    equipment_details = None if message.text.strip().lower() == "/skip" else message.text.strip()
    await state.update_data(equipment_details=equipment_details)

    await _ask_limitations(message, state, language)


@router.message(ProfileStates.waiting_for_limitations)
async def handle_profile_limitations(message: Message, state: FSMContext) -> None:
    """Вопрос 3, ответ свободным текстом."""
    user_id = message.from_user.id
    language = await _get_language(user_id, message.from_user)
    await _finish_profile_survey(message, state, user_id, language, limitations=message.text.strip())


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
