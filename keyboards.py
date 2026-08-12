"""Inline/reply-клавиатуры, список команд бота и локализованные тексты меню."""

from typing import Optional

from aiogram.types import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from exercises_data import EXERCISE_CATEGORIES, get_category_name, get_exercise_display_name, pick_language
from program import split_label
from utils import pluralize_sets

CATEGORY_CALLBACK_PREFIX = "cat"
EXERCISE_CALLBACK_PREFIX = "ex"
CUSTOM_EXERCISE_CALLBACK_PREFIX = "cx"
ADD_CUSTOM_CALLBACK_PREFIX = "custom"
BACK_TO_CATEGORIES_CALLBACK = "back_categories"
LANGUAGE_CALLBACK_PREFIX = "lang"
PROGRAM_SOURCE_CALLBACK_PREFIX = "prog_src"
PROGRAM_GOAL_CALLBACK_PREFIX = "prog_goal"
EQUIPMENT_CALLBACK_PREFIX = "equip"
LIMITATIONS_NONE_CALLBACK = "limitations_none"
FREQUENCY_CALLBACK_PREFIX = "freq"
SPLIT_CHOICE_CALLBACK_PREFIX = "split_choice"
SPLIT_CONTINUE_LOCKED_CALLBACK = "split_continue_locked"
SPLIT_LEARN_PREMIUM_CALLBACK = "split_learn_premium"
SPLIT_GOAL_CALLBACK_PREFIX = "split_goal"
UPDATE_PROFILE_CTA_CALLBACK = "update_profile_cta"

_ADD_CUSTOM_LABEL = {"ru": "➕ Добавить своё упражнение", "en": "➕ Add your own exercise", "fr": "➕ Ajouter mon exercice"}
_BACK_LABEL = {"ru": "⬅️ Назад к категориям", "en": "⬅️ Back to categories", "fr": "⬅️ Retour aux catégories"}
_CHOOSE_CATEGORY_TEXT = {
    "ru": "Выбери категорию упражнений:",
    "en": "Choose an exercise category:",
    "fr": "Choisis une catégorie d'exercice :",
}
_CHOOSE_EXERCISE_TEXT = {
    "ru": "Категория «{category}». Выбери упражнение:",
    "en": "Category: {category}. Choose an exercise:",
    "fr": "Catégorie : {category}. Choisis un exercice :",
}
_ASK_CUSTOM_NAME_TEXT = {
    "ru": "Напиши название упражнения:",
    "en": "Type the exercise name:",
    "fr": "Écris le nom de l'exercice :",
}
_OPEN_WEBAPP_LABEL = {
    "ru": "🌐 Открыть меню упражнений",
    "en": "🌐 Open exercises menu",
    "fr": "🌐 Ouvrir le menu des exercices",
}

_ASK_PROGRAM_SOURCE_TEXT = {
    "ru": "Как составить программу?",
    "en": "How should I build your program?",
    "fr": "Comment veux-tu construire ton programme ?",
}
_PROGRAM_SOURCE_LABELS = {
    "goal": {"ru": "🎯 По цели", "en": "🎯 By goal", "fr": "🎯 Selon un objectif"},
    "history": {
        "ru": "📈 На основе моей истории тренировок",
        "en": "📈 Based on my workout history",
        "fr": "📈 Selon mon historique d'entraînement",
    },
    "split": {
        "ru": "🗓 Сплит на неделю",
        "en": "🗓 Weekly split",
        "fr": "🗓 Split hebdomadaire",
    },
}
_ASK_PROGRAM_GOAL_TEXT = {
    "ru": "Какая у тебя цель?",
    "en": "What's your goal?",
    "fr": "Quel est ton objectif ?",
}
_PROGRAM_GOAL_LABELS = {
    "bulk": {"ru": "💪 Набрать массу", "en": "💪 Build muscle", "fr": "💪 Prendre du muscle"},
    "cut": {"ru": "🔥 Похудеть", "en": "🔥 Lose weight", "fr": "🔥 Perdre du poids"},
    "endurance": {"ru": "🏃 Выносливость", "en": "🏃 Endurance", "fr": "🏃 Endurance"},
}
_NO_SAVED_PROGRAM_TEXT = {
    "ru": "У тебя пока нет сохранённой программы — набери /program, чтобы я её составил.",
    "en": "You don't have a saved program yet — try /program and I'll put one together.",
    "fr": "Tu n'as pas encore de programme enregistré — essaie /program et je t'en prépare un.",
}

# ---------------------------------------------------------------------------
# Мини-опрос профиля (опыт/оборудование/ограничения) — один раз перед первой
# генерацией программы, см. states.ProfileStates и handlers.py
# ---------------------------------------------------------------------------

_ASK_EXPERIENCE_TEXT = {
    "ru": "Для начала — короткий опрос, разово, чтобы программа была под тебя. Сколько месяцев/лет ты уже ходишь в зал?",
    "en": "First — a quick one-time survey so your program actually fits you. How many months/years have you been training?",
    "fr": "D'abord — un petit questionnaire ponctuel pour que ton programme te corresponde. Depuis combien de mois/années t'entraînes-tu ?",
}
_ASK_EQUIPMENT_TEXT = {
    "ru": "Какое оборудование у тебя есть?",
    "en": "What equipment do you have access to?",
    "fr": "Quel équipement as-tu à disposition ?",
}
_EQUIPMENT_LABELS = {
    "free_weights": {
        "ru": "🏋️ Только свободные веса (гантели/штанга)",
        "en": "🏋️ Free weights only (dumbbells/barbell)",
        "fr": "🏋️ Poids libres uniquement (haltères/barre)",
    },
    "machines": {"ru": "🎛 Только тренажёры", "en": "🎛 Machines only", "fr": "🎛 Machines uniquement"},
    "full_gym": {"ru": "🏟 Полный зал", "en": "🏟 Full gym", "fr": "🏟 Salle complète"},
    "home": {
        "ru": "🏠 Домашние условия / минимум инвентаря",
        "en": "🏠 Home / minimal equipment",
        "fr": "🏠 À la maison / équipement minimal",
    },
}
_ASK_EQUIPMENT_DETAILS_TEXT = {
    "ru": "Хочешь уточнить точнее? Напиши какое конкретно оборудование доступно, или пропусти этот шаг командой /skip",
    "en": "Want to be more specific? Type exactly what equipment you have, or skip this step with /skip",
    "fr": "Tu veux préciser ? Écris quel équipement exactement tu as, ou passe cette étape avec /skip",
}
_ASK_LIMITATIONS_TEXT = {
    "ru": "Есть травмы или ограничения, на которые стоит обратить внимание?",
    "en": "Any injuries or limitations I should know about?",
    "fr": "As-tu des blessures ou limitations à prendre en compte ?",
}
_LIMITATIONS_NONE_LABEL = {"ru": "🚫 Нет", "en": "🚫 None", "fr": "🚫 Aucune"}
_PROFILE_SAVED_TEXT = {
    "ru": "Готово, профиль сохранён! Учту это при составлении программы 💪 (обновить можно в любой момент командой /update_profile)",
    "en": "Done, profile saved! I'll factor this in when building your program 💪 (update it anytime with /update_profile)",
    "fr": "C'est fait, profil enregistré ! J'en tiendrai compte pour ton programme 💪 (modifiable à tout moment avec /update_profile)",
}
_SPLIT_FEATURE_HINT_TEXT = {
    "ru": "Кстати, теперь можно собрать программу по сплиту (частота тренировок в неделю) — попробуй /program 💪",
    "en": "By the way, you can now build a program based on a split (weekly training frequency) — try /program 💪",
    "fr": "Au fait, tu peux maintenant construire un programme basé sur un split (fréquence d'entraînement hebdomadaire) — essaie /program 💪",
}

# ---------------------------------------------------------------------------
# "Сплит на неделю" — частота тренировок (лениво, при первом выборе этой ветки в
# /program) и выбор/подтверждение сплита, см. states.ProgramStates, handlers.py,
# program.get_split_options
# ---------------------------------------------------------------------------

_ASK_FREQUENCY_TEXT = {
    "ru": "Сколько раз в неделю готов ходить в зал?",
    "en": "How many times a week are you up for training?",
    "fr": "Combien de fois par semaine peux-tu t'entraîner ?",
}
_FREQUENCY_LABELS = {
    "1-2": {"ru": "1-2 раза", "en": "1-2 times", "fr": "1-2 fois"},
    "3": {"ru": "3 раза", "en": "3 times", "fr": "3 fois"},
    "4": {"ru": "4 раза", "en": "4 times", "fr": "4 fois"},
    "5-6": {"ru": "5-6 раз", "en": "5-6 times", "fr": "5-6 fois"},
}
_ASK_SPLIT_CHOICE_TEXT = {
    "ru": "На основе твоих ответов тебе доступно несколько вариантов сплита. Выбери:",
    "en": "Based on your answers, a few split options are available. Pick one:",
    "fr": "D'après tes réponses, plusieurs types de split sont possibles. Choisis :",
}
_SPLIT_LOCKED_INTRO_TEXT = {
    "ru": "На основе твоих ответов тебе доступно несколько вариантов сплита:",
    "en": "Based on your answers, a few split options would be available:",
    "fr": "D'après tes réponses, plusieurs types de split seraient possibles :",
}
_SPLIT_LOCKED_OUTRO_TEXT = {
    "ru": "Без premium — соберём {split} программу (тоже рабочий вариант).",
    "en": "Without premium — we'll build a {split} program (still a solid option).",
    "fr": "Sans premium — on te prépare un programme {split} (une option qui marche aussi).",
}
_SPLIT_CONTINUE_LOCKED_LABEL = {
    "ru": "Продолжить с {split}",
    "en": "Continue with {split}",
    "fr": "Continuer avec {split}",
}
_SPLIT_LEARN_PREMIUM_LABEL = {"ru": "Узнать про Premium →", "en": "Learn about Premium →", "fr": "En savoir plus sur Premium →"}
_SPLIT_PREMIUM_INFO_TEXT = {
    "ru": "Premium пока не запущен, но скоро будет доступен — там появится реальный выбор сплита, сокращение программы и другие фишки. Пока продолжаем на бесплатном варианте:",
    "en": "Premium isn't live yet, but it's coming soon — real split choice, shortening the program, and more. For now, let's continue on the free option:",
    "fr": "Premium n'est pas encore disponible, mais ça arrive — vrai choix de split, réduction du programme, et plus. En attendant, on continue avec l'option gratuite :",
}
_ASK_SPLIT_GOAL_TEXT = {
    "ru": "Какая цель на эту программу?",
    "en": "What's the goal for this program?",
    "fr": "Quel est l'objectif de ce programme ?",
}
_SPLIT_GOAL_LABELS = {
    "build_muscle": {"ru": "💪 Набрать массу", "en": "💪 Build muscle", "fr": "💪 Prendre du muscle"},
    "lose_weight": {"ru": "🔥 Похудеть", "en": "🔥 Lose weight", "fr": "🔥 Perdre du poids"},
    "strength": {"ru": "🏋️ Сила", "en": "🏋️ Strength", "fr": "🏋️ Force"},
}

# Языковые кнопки: (код языка, подпись). Показывается ДО того, как язык известен,
# поэтому подписи содержат флаг и название языка на нём самом — понятно без перевода.
LANGUAGE_BUTTONS = [
    ("ru", "🇷🇺 Русский"),
    ("en", "🇬🇧 English"),
    ("fr", "🇫🇷 Français"),
]

# Само приглашение выбрать язык дано сразу на всех трёх языках — оно показывается
# до того, как язык пользователя вообще известен
_CHOOSE_LANGUAGE_TEXT = (
    "🇷🇺 Выбери язык интерфейса:\n"
    "🇬🇧 Choose your interface language:\n"
    "🇫🇷 Choisis la langue de l'interface :"
)

# Минимальное приветствие ДО выбора языка (см. cmd_start) — тоже на всех трёх языках сразу,
# т.к. язык пользователя ещё не известен. Пересобранный онбординг (см. handlers.py):
# приветствие -> выбор языка -> мини-опрос профиля -> переход в Web App -> объяснение
# трекинга при первом сообщении после онбординга. Ничего про кнопки постоянного меню или
# "ещё один подход" здесь намеренно не объясняется — кнопки видны физически без слов.
_PRE_LANGUAGE_GREETING_TEXT = (
    "🇷🇺 Привет! Я LiftMate 💪 — отслеживаю твои тренировки и слежу за прогрессом.\n"
    "🇬🇧 Hi! I'm LiftMate 💪 — I track your workouts and keep an eye on your progress.\n"
    "🇫🇷 Salut ! Je suis LiftMate 💪 — je suis tes entraînements et ta progression."
)

# То же приветствие, но на одном языке — для повторных /start ПОСЛЕ того, как язык уже
# выбран (и для новых, и для уже онбордившихся пользователей, см. cmd_start).
_MINIMAL_WELCOME_TEXT = {
    "ru": "Привет! Я LiftMate 💪 — отслеживаю твои тренировки и слежу за прогрессом.",
    "en": "Hi! I'm LiftMate 💪 — I track your workouts and keep an eye on your progress.",
    "fr": "Salut ! Je suis LiftMate 💪 — je suis tes entraînements et ta progression.",
}

# Повторный /start (язык уже сохранён, т.е. онбординг когда-то уже пройден) — короткая
# подсказка "продолжай как обычно" вместо старого большого welcome_text, который раньше
# перечислял кнопки/фичи текстом. Показывается ТОЛЬКО в этой ветке cmd_start — на самом
# онбординге (когда язык ещё выбирается впервые) не участвует.
_RETURNING_USER_HINT_TEXT = {
    "ru": "Кнопки внизу под рукой — можешь продолжать трекать тренировки как обычно, просто опиши подход текстом.",
    "en": "The buttons below are right there — keep tracking as usual, just describe your set in a message.",
    "fr": "Les boutons ci-dessous sont à portée de main — continue à suivre tes séances comme d'habitude, décris simplement ta série.",
}

# Кнопка "Обновить профиль" на сообщении повторного /start (см. UPDATE_PROFILE_CTA_CALLBACK) —
# ведёт в тот же мини-опрос профиля, что и команда /update_profile (см.
# handlers.handle_update_profile_cta, переиспользует _start_profile_survey напрямую).
_UPDATE_PROFILE_CTA_LABEL = {
    "ru": "🔄 Обновить профиль",
    "en": "🔄 Update profile",
    "fr": "🔄 Mettre à jour le profil",
}

# Интро мини-опроса профиля специально для онбординга (сразу после выбора языка) — без
# призыва в духе "погнали" и без предположения, что пользователь прямо сейчас в зале.
# Объединяет вводную фразу и первый вопрос опроса в одно сообщение (тот же вопрос, что и
# в _ASK_EXPERIENCE_TEXT, но без рамки "чтобы программа была под тебя" — на этом этапе речь
# ещё не о конкретной программе тренировок).
_ONBOARDING_PROFILE_INTRO_TEXT = {
    "ru": "Для начала — пара вопросов о тебе, чтобы всё было по делу (займёт минуту):\n\nСколько месяцев/лет ты уже ходишь в зал?",
    "en": "First — a couple of questions about you, so things stay relevant (takes a minute):\n\nHow many months/years have you been training?",
    "fr": "D'abord — quelques questions sur toi, pour que ce soit pertinent (ça prend une minute) :\n\nDepuis combien de mois/années t'entraînes-tu ?",
}

# Показывается сразу после сохранения профиля, если опрос запущен из онбординга (а не из
# /program или /update_profile) — переход в Web App вместо продолжения диалога программы.
_ONBOARDING_WEBAPP_CTA_TEXT = {
    "ru": "Готово! Загляни в приложение — там профиль и первые шаги.",
    "en": "All set! Check out the app — your profile and first steps are there.",
    "fr": "C'est fait ! Jette un œil à l'application — ton profil et tes premiers pas y sont.",
}

_OPEN_WEBAPP_ONBOARDING_LABEL = {
    "ru": "📱 Открыть приложение",
    "en": "📱 Open the app",
    "fr": "📱 Ouvrir l'application",
}

# Одноразовое объяснение, как трекать тренировки текстом — раньше жило в общем приветствии,
# теперь показывается перед разбором ПЕРВОГО сообщения после онбординга (см.
# handlers._process_new_message, database.has_seen_tracking_intro/mark_tracking_intro_shown).
_TRACKING_INTRO_TEXT = {
    "ru": "Когда будешь в зале — просто напиши мне, что сделал(а): «жим 80 на 8». Я запомню и в следующий раз подскажу, что улучшить.",
    "en": "When you're at the gym — just tell me what you did: \"bench 80 for 8\". I'll remember it and suggest improvements next time.",
    "fr": "Quand tu seras à la salle — dis-moi simplement ce que tu as fait : « développé 80 pour 8 ». Je m'en souviendrai et te donnerai des conseils la prochaine fois.",
}

_LANGUAGE_CONFIRMED_TEXT = {
    "ru": "✅ Готово, теперь буду общаться на русском! Сменить язык можно в любой момент командой /language.",
    "en": "✅ Done, I'll speak English from now on! You can change the language anytime with /language.",
    "fr": "✅ Parfait, je vais parler français désormais ! Tu peux changer de langue à tout moment avec /language.",
}

_KEYBOARD_HINT_TEXT = {
    "ru": "Кнопки меню внизу обновлены 👇",
    "en": "The menu buttons below are updated 👇",
    "fr": "Les boutons du menu ci-dessous sont à jour 👇",
}

# ---------------------------------------------------------------------------
# Список команд бота (нативное меню Telegram при вводе "/") — регистрируется
# через bot.set_my_commands(..., language_code=...) в main.py
# ---------------------------------------------------------------------------

_BOT_COMMANDS = {
    "ru": [
        BotCommand(command="start", description="Начать сначала"),
        BotCommand(command="exercises", description="Меню упражнений"),
        BotCommand(command="program", description="Программа тренировки на сегодня"),
        BotCommand(command="my_program", description="Последняя сохранённая программа"),
        BotCommand(command="update_profile", description="Обновить профиль (опыт/оборудование)"),
        BotCommand(command="leaderboard", description="Таблица лидеров"),
        BotCommand(command="language", description="Сменить язык"),
    ],
    "en": [
        BotCommand(command="start", description="Restart"),
        BotCommand(command="exercises", description="Exercise menu"),
        BotCommand(command="program", description="Today's workout program"),
        BotCommand(command="my_program", description="Your last saved program"),
        BotCommand(command="update_profile", description="Update profile (experience/equipment)"),
        BotCommand(command="leaderboard", description="Streak leaderboard"),
        BotCommand(command="language", description="Change language"),
    ],
    "fr": [
        BotCommand(command="start", description="Recommencer"),
        BotCommand(command="exercises", description="Menu des exercices"),
        BotCommand(command="program", description="Programme d'entraînement du jour"),
        BotCommand(command="my_program", description="Dernier programme enregistré"),
        BotCommand(command="update_profile", description="Mettre à jour le profil (expérience/équipement)"),
        BotCommand(command="leaderboard", description="Classement des séries"),
        BotCommand(command="language", description="Changer de langue"),
    ],
}

# ---------------------------------------------------------------------------
# Постоянная Reply-клавиатура (кнопки внизу экрана — алиасы команд)
# ---------------------------------------------------------------------------

_REPLY_BUTTON_LABELS = {
    "exercises": {"ru": "📋 Упражнения", "en": "📋 Exercises", "fr": "📋 Exercices"},
    "leaderboard": {"ru": "🏆 Лидерборд", "en": "🏆 Leaderboard", "fr": "🏆 Classement"},
    "program": {"ru": "🗓 Программа", "en": "🗓 Program", "fr": "🗓 Programme"},
    "language": {"ru": "🌐 Язык", "en": "🌐 Language", "fr": "🌐 Langue"},
}

# Плоский набор всех подписей кнопок на всех языках — чтобы узнавать нажатие
# независимо от того, на каком языке сейчас отрисована клавиатура у пользователя
ALL_REPLY_BUTTON_TEXTS = frozenset(
    label for labels in _REPLY_BUTTON_LABELS.values() for label in labels.values()
)



def _localized(mapping: dict, language: str, **kwargs) -> str:
    text = mapping[pick_language(language)]
    return text.format(**kwargs) if kwargs else text


def build_categories_keyboard(language: str, webapp_url: str) -> InlineKeyboardMarkup:
    """
    Клавиатура со всеми категориями упражнений, по 2 кнопки в ряд, и отдельной
    верхней кнопкой, которая открывает полноценный Web App (тот же выбор
    упражнений, но в виде отдельного веб-интерфейса внутри Telegram).
    """
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(
            text=_localized(_OPEN_WEBAPP_LABEL, language),
            web_app=WebAppInfo(url=webapp_url),
        )
    )

    for category_key in EXERCISE_CATEGORIES:
        builder.button(
            text=get_category_name(category_key, language),
            callback_data=f"{CATEGORY_CALLBACK_PREFIX}:{category_key}",
        )
    # Первая строка (Web App) уже зафиксирована через .row(), поэтому adjust
    # применяется только к последующим кнопкам категорий — по 2 в ряд
    builder.adjust(1, 2)
    return builder.as_markup()


def build_exercises_keyboard(category_key: str, language: str, custom_exercises: list) -> InlineKeyboardMarkup:
    """
    Клавиатура со списком упражнений категории (по одной кнопке в ряд), затем
    пользовательскими упражнениями этой категории (если есть), и кнопками
    "Добавить своё упражнение" / "Назад к категориям".
    """
    builder = InlineKeyboardBuilder()

    for exercise in EXERCISE_CATEGORIES[category_key]["exercises"]:
        builder.button(
            text=get_exercise_display_name(exercise, language),
            callback_data=f"{EXERCISE_CALLBACK_PREFIX}:{category_key}:{exercise['key']}",
        )

    for custom in custom_exercises:
        builder.button(
            text=custom["exercise_name"].capitalize(),
            callback_data=f"{CUSTOM_EXERCISE_CALLBACK_PREFIX}:{custom['id']}",
        )

    builder.button(
        text=_localized(_ADD_CUSTOM_LABEL, language),
        callback_data=f"{ADD_CUSTOM_CALLBACK_PREFIX}:{category_key}",
    )
    builder.button(text=_localized(_BACK_LABEL, language), callback_data=BACK_TO_CATEGORIES_CALLBACK)

    builder.adjust(1)
    return builder.as_markup()


def choose_category_text(language: str) -> str:
    """Заголовок для клавиатуры категорий."""
    return _localized(_CHOOSE_CATEGORY_TEXT, language)


def choose_exercise_text(category_key: str, language: str) -> str:
    """Заголовок для клавиатуры упражнений выбранной категории."""
    category_name = get_category_name(category_key, language)
    return _localized(_CHOOSE_EXERCISE_TEXT, language, category=category_name)


def ask_custom_name_text(language: str) -> str:
    """Просьба написать название своего упражнения текстом."""
    return _localized(_ASK_CUSTOM_NAME_TEXT, language)


def build_language_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора языка интерфейса — 3 кнопки, по одной в ряд."""
    builder = InlineKeyboardBuilder()
    for code, label in LANGUAGE_BUTTONS:
        builder.button(text=label, callback_data=f"{LANGUAGE_CALLBACK_PREFIX}:{code}")
    builder.adjust(1)
    return builder.as_markup()


def choose_language_text() -> str:
    """Приглашение выбрать язык — сразу на всех трёх языках, чтобы было понятно любому пользователю."""
    return _CHOOSE_LANGUAGE_TEXT


def pre_language_greeting_text() -> str:
    """Минимальное приветствие ДО выбора языка — на всех трёх языках сразу (см. cmd_start)."""
    return _PRE_LANGUAGE_GREETING_TEXT


def language_confirmed_text(language: str) -> str:
    """Подтверждение того, что язык интерфейса сохранён."""
    return _localized(_LANGUAGE_CONFIRMED_TEXT, language)


def minimal_welcome_text(language: str) -> str:
    """Минимальное приветствие /start на выбранном языке — и для новых, и для уже онбордившихся пользователей."""
    return _localized(_MINIMAL_WELCOME_TEXT, language)


def returning_user_hint_text(language: str) -> str:
    """Короткая подсказка "продолжай как обычно" для повторного /start (язык уже сохранён)."""
    return _localized(_RETURNING_USER_HINT_TEXT, language)


def build_returning_user_keyboard(language: str) -> InlineKeyboardMarkup:
    """Клавиатура с единственной кнопкой "Обновить профиль" для сообщения повторного /start."""
    builder = InlineKeyboardBuilder()
    builder.button(text=_localized(_UPDATE_PROFILE_CTA_LABEL, language), callback_data=UPDATE_PROFILE_CTA_CALLBACK)
    return builder.as_markup()


def update_profile_cta_label(language: str) -> str:
    """Подпись кнопки "Обновить профиль" — для подтверждения нажатия ("✅ ...")."""
    return _localized(_UPDATE_PROFILE_CTA_LABEL, language)


def onboarding_profile_intro_text(language: str) -> str:
    """Вводная фраза + первый вопрос мини-опроса профиля, специально для онбординга (см. cmd_start)."""
    return _localized(_ONBOARDING_PROFILE_INTRO_TEXT, language)


def onboarding_webapp_cta_text(language: str) -> str:
    """Текст перехода в Web App сразу после мини-опроса профиля в рамках онбординга."""
    return _localized(_ONBOARDING_WEBAPP_CTA_TEXT, language)


def build_onboarding_webapp_keyboard(language: str, webapp_url: str) -> InlineKeyboardMarkup:
    """Клавиатура с единственной кнопкой, открывающей Web App — для перехода в конце онбординга."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=_localized(_OPEN_WEBAPP_ONBOARDING_LABEL, language),
        web_app=WebAppInfo(url=webapp_url),
    )
    return builder.as_markup()


def tracking_intro_text(language: str) -> str:
    """Одноразовое объяснение, как трекать тренировки текстом (см. _process_new_message)."""
    return _localized(_TRACKING_INTRO_TEXT, language)


def keyboard_hint_text(language: str) -> str:
    """Короткая подпись при обновлении подписей постоянной клавиатуры (после смены языка)."""
    return _localized(_KEYBOARD_HINT_TEXT, language)


def get_commands(language: str) -> list:
    """Список команд бота (BotCommand) для нативного меню Telegram на заданном языке."""
    return _BOT_COMMANDS[pick_language(language)]


def build_main_reply_keyboard(language: str) -> ReplyKeyboardMarkup:
    """
    Постоянная клавиатура внизу экрана — кнопки-алиасы для /exercises, /leaderboard,
    /program и /language. Два ряда по 2 кнопки, чтобы не было тесно на маленьких экранах.
    resize_keyboard=True, чтобы не занимала лишнее место.
    """
    lang = pick_language(language)

    def _row(actions: tuple) -> list:
        return [KeyboardButton(text=_REPLY_BUTTON_LABELS[action][lang]) for action in actions]

    return ReplyKeyboardMarkup(
        keyboard=[_row(("exercises", "leaderboard")), _row(("program", "language"))],
        resize_keyboard=True,
    )


def match_reply_button(text: str) -> Optional[str]:
    """
    Возвращает "exercises"/"leaderboard"/"language", если text совпадает с подписью
    одной из кнопок постоянной клавиатуры (на любом из трёх языков), иначе None.
    """
    for action, labels in _REPLY_BUTTON_LABELS.items():
        if text in labels.values():
            return action
    return None


def build_program_source_keyboard(language: str) -> InlineKeyboardMarkup:
    """Клавиатура выбора способа составления программы: "по цели", "на основе истории" или "сплит на неделю"."""
    builder = InlineKeyboardBuilder()
    for source_key in ("goal", "history", "split"):
        builder.button(
            text=_localized(_PROGRAM_SOURCE_LABELS[source_key], language),
            callback_data=f"{PROGRAM_SOURCE_CALLBACK_PREFIX}:{source_key}",
        )
    builder.adjust(1)
    return builder.as_markup()


def build_program_goal_keyboard(language: str) -> InlineKeyboardMarkup:
    """Клавиатура выбора цели ("по цели" -> набрать массу / похудеть / выносливость)."""
    builder = InlineKeyboardBuilder()
    for goal_key in _PROGRAM_GOAL_LABELS:
        builder.button(
            text=_localized(_PROGRAM_GOAL_LABELS[goal_key], language),
            callback_data=f"{PROGRAM_GOAL_CALLBACK_PREFIX}:{goal_key}",
        )
    builder.adjust(1)
    return builder.as_markup()


def ask_program_source_text(language: str) -> str:
    """Первый вопрос диалога /program: как составить программу."""
    return _localized(_ASK_PROGRAM_SOURCE_TEXT, language)


def ask_program_goal_text(language: str) -> str:
    """Второй вопрос (после "по цели"): какая именно цель."""
    return _localized(_ASK_PROGRAM_GOAL_TEXT, language)


def program_source_label(source_key: str, language: str) -> str:
    """Подпись выбранного способа составления — для подтверждения выбора ("✅ ...")."""
    return _localized(_PROGRAM_SOURCE_LABELS[source_key], language)


def program_goal_label(goal_key: str, language: str) -> str:
    """Подпись выбранной цели — для подтверждения выбора ("✅ ...")."""
    return _localized(_PROGRAM_GOAL_LABELS[goal_key], language)


def no_saved_program_text(language: str) -> str:
    """Ответ на /my_program, если у пользователя ещё нет сохранённой программы."""
    return _localized(_NO_SAVED_PROGRAM_TEXT, language)


def ask_experience_text(language: str) -> str:
    """Вопрос 1 мини-опроса профиля: стаж тренировок (свободный текст)."""
    return _localized(_ASK_EXPERIENCE_TEXT, language)


def ask_equipment_text(language: str) -> str:
    """Вопрос 2 мини-опроса профиля: какое оборудование доступно."""
    return _localized(_ASK_EQUIPMENT_TEXT, language)


def build_equipment_keyboard(language: str) -> InlineKeyboardMarkup:
    """Клавиатура выбора типа оборудования (по одной кнопке в ряд)."""
    builder = InlineKeyboardBuilder()
    for equipment_key in _EQUIPMENT_LABELS:
        builder.button(
            text=_localized(_EQUIPMENT_LABELS[equipment_key], language),
            callback_data=f"{EQUIPMENT_CALLBACK_PREFIX}:{equipment_key}",
        )
    builder.adjust(1)
    return builder.as_markup()


def equipment_label(equipment_key: str, language: str) -> str:
    """Подпись выбранного оборудования — для подтверждения выбора ("✅ ...")."""
    return _localized(_EQUIPMENT_LABELS[equipment_key], language)


def ask_equipment_details_text(language: str) -> str:
    """Уточняющий вопрос после выбора типа оборудования (свободный текст или /skip)."""
    return _localized(_ASK_EQUIPMENT_DETAILS_TEXT, language)


def ask_limitations_text(language: str) -> str:
    """Вопрос 3 мини-опроса профиля: травмы/ограничения (свободный текст или кнопка "Нет")."""
    return _localized(_ASK_LIMITATIONS_TEXT, language)


def build_limitations_keyboard(language: str) -> InlineKeyboardMarkup:
    """Клавиатура с единственной кнопкой "Нет" — альтернатива свободному текстовому ответу."""
    builder = InlineKeyboardBuilder()
    builder.button(text=_localized(_LIMITATIONS_NONE_LABEL, language), callback_data=LIMITATIONS_NONE_CALLBACK)
    return builder.as_markup()


def limitations_none_label(language: str) -> str:
    """Подпись кнопки "Нет" — для подтверждения выбора ("✅ ...")."""
    return _localized(_LIMITATIONS_NONE_LABEL, language)


def profile_saved_text(language: str) -> str:
    """Подтверждение того, что профиль сохранён (конец мини-опроса /program или /update_profile)."""
    return _localized(_PROFILE_SAVED_TEXT, language)


def split_feature_hint_text(language: str) -> str:
    """
    Подсказка про "Сплит на неделю" — добавляется к подтверждению /update_profile, только
    пока пользователь ни разу не проходил через неё (days_per_week всё ещё NULL), см.
    handlers._finish_profile_survey.
    """
    return _localized(_SPLIT_FEATURE_HINT_TEXT, language)


def ask_frequency_text(language: str) -> str:
    """Вопрос про частоту тренировок в неделю — лениво, при первом выборе "Сплит на неделю"."""
    return _localized(_ASK_FREQUENCY_TEXT, language)


def build_frequency_keyboard(language: str) -> InlineKeyboardMarkup:
    """Клавиатура выбора частоты: [1-2] [3] [4] [5-6], по 2 кнопки в ряд."""
    builder = InlineKeyboardBuilder()
    for freq_key in ("1-2", "3", "4", "5-6"):
        builder.button(
            text=_localized(_FREQUENCY_LABELS[freq_key], language),
            callback_data=f"{FREQUENCY_CALLBACK_PREFIX}:{freq_key}",
        )
    builder.adjust(2, 2)
    return builder.as_markup()


def frequency_label(freq_key: str, language: str) -> str:
    """Подпись выбранной частоты — для подтверждения выбора ("✅ ...")."""
    return _localized(_FREQUENCY_LABELS[freq_key], language)


def ask_split_choice_text(language: str) -> str:
    """Вопрос выбора сплита — реальный выбор, показывается только premium (см. get_split_options)."""
    return _localized(_ASK_SPLIT_CHOICE_TEXT, language)


def build_split_choice_keyboard(options: list, language: str) -> InlineKeyboardMarkup:
    """Реальный выбор сплита (только premium) — по кнопке на каждый вариант из options."""
    builder = InlineKeyboardBuilder()
    for split_key in options:
        builder.button(
            text=split_label(split_key, language),
            callback_data=f"{SPLIT_CHOICE_CALLBACK_PREFIX}:{split_key}",
        )
    builder.adjust(1)
    return builder.as_markup()


def split_locked_message(options: list, fixed_split: str, language: str) -> str:
    """
    Апселл-сообщение для free-пользователя: показывает, какие сплиты БЫЛИ БЫ доступны
    (помечены 🔒), и что вместо них будет использован fixed_split (см. get_split_options).
    """
    lines = [_localized(_SPLIT_LOCKED_INTRO_TEXT, language), ""]
    for split_key in options:
        lines.append(f"🔒 {split_label(split_key, language)} — premium")
    lines.append("")
    lines.append(_localized(_SPLIT_LOCKED_OUTRO_TEXT, language, split=split_label(fixed_split, language)))
    return "\n".join(lines)


def build_split_locked_keyboard(fixed_split: str, language: str) -> InlineKeyboardMarkup:
    """Кнопки под апселл-сообщением: "Продолжить с {фиксированный сплит}" / "Узнать про Premium"."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=_localized(_SPLIT_CONTINUE_LOCKED_LABEL, language, split=split_label(fixed_split, language)),
        callback_data=SPLIT_CONTINUE_LOCKED_CALLBACK,
    )
    builder.button(
        text=_localized(_SPLIT_LEARN_PREMIUM_LABEL, language),
        callback_data=SPLIT_LEARN_PREMIUM_CALLBACK,
    )
    builder.adjust(1)
    return builder.as_markup()


def split_premium_info_text(language: str) -> str:
    """Заглушка-объяснение при нажатии "Узнать про Premium" (реальный premium ещё не запущен)."""
    return _localized(_SPLIT_PREMIUM_INFO_TEXT, language)


def ask_split_goal_text(language: str) -> str:
    """Вопрос цели именно в рамках сплит-флоу (после определения сплита)."""
    return _localized(_ASK_SPLIT_GOAL_TEXT, language)


def build_split_goal_keyboard(language: str) -> InlineKeyboardMarkup:
    """Клавиатура выбора цели для сплит-программы: набрать массу / похудеть / сила."""
    builder = InlineKeyboardBuilder()
    for goal_key in _SPLIT_GOAL_LABELS:
        builder.button(
            text=_localized(_SPLIT_GOAL_LABELS[goal_key], language),
            callback_data=f"{SPLIT_GOAL_CALLBACK_PREFIX}:{goal_key}",
        )
    builder.adjust(1)
    return builder.as_markup()


def split_goal_label(goal_key: str, language: str) -> str:
    """Подпись выбранной цели сплит-программы — для подтверждения выбора ("✅ ...")."""
    return _localized(_SPLIT_GOAL_LABELS[goal_key], language)


def format_last_result(row: dict, language: str) -> str:
    """Короткая фраза с последним результатом по упражнению перед новым подходом."""
    lang = pick_language(language)
    weight, reps, sets = row["weight"], row["reps"], row["sets"]

    if lang == "ru":
        return f"Твой последний результат: {weight:g}кг × {reps}, {sets} {pluralize_sets(sets)}."
    if lang == "fr":
        sets_word = "série" if sets == 1 else "séries"
        return f"Ton dernier résultat : {weight:g}kg × {reps}, {sets} {sets_word}."

    sets_word = "set" if sets == 1 else "sets"
    return f"Your last result: {weight:g}kg × {reps}, {sets} {sets_word}."
