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
from utils import pluralize_sets

CATEGORY_CALLBACK_PREFIX = "cat"
EXERCISE_CALLBACK_PREFIX = "ex"
CUSTOM_EXERCISE_CALLBACK_PREFIX = "cx"
ADD_CUSTOM_CALLBACK_PREFIX = "custom"
BACK_TO_CATEGORIES_CALLBACK = "back_categories"
LANGUAGE_CALLBACK_PREFIX = "lang"

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
        BotCommand(command="leaderboard", description="Таблица лидеров"),
        BotCommand(command="language", description="Сменить язык"),
    ],
    "en": [
        BotCommand(command="start", description="Restart"),
        BotCommand(command="exercises", description="Exercise menu"),
        BotCommand(command="leaderboard", description="Streak leaderboard"),
        BotCommand(command="language", description="Change language"),
    ],
    "fr": [
        BotCommand(command="start", description="Recommencer"),
        BotCommand(command="exercises", description="Menu des exercices"),
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
    "language": {"ru": "🌐 Язык", "en": "🌐 Language", "fr": "🌐 Langue"},
}

# Плоский набор всех подписей кнопок на всех языках — чтобы узнавать нажатие
# независимо от того, на каком языке сейчас отрисована клавиатура у пользователя
ALL_REPLY_BUTTON_TEXTS = frozenset(
    label for labels in _REPLY_BUTTON_LABELS.values() for label in labels.values()
)

_WELCOME_TEXT = {
    "ru": (
        "Я LiftMate — бот для трекинга твоих тренировок в зале. 💪\n\n"
        "Можешь писать мне о выполненном подходе в свободной форме, например:\n"
        "«жим лежа 80кг на 8 раз, 3 подхода»\n"
        "«сделал присед 100 на 5»\n\n"
        "А можешь вообще не запоминать команды — теперь внизу экрана есть постоянные "
        "кнопки: 📋 Упражнения, 🏆 Лидерборд и 🌐 Язык. Плюс синяя "
        "кнопка меню слева от поля ввода тоже открывает полноценный интерфейс с "
        "упражнениями прямо внутри Telegram.\n\n"
        "Если забудешь указать вес, повторения или количество подходов — я переспрошу. "
        "А если просто допишешь что-то вроде «ещё один подход» — пойму, что речь про "
        "последнее упражнение, и обновлю запись.\n\n"
        "Сменить язык интерфейса можно в любой момент командой /language или кнопкой 🌐. Погнали!"
    ),
    "en": (
        "I'm LiftMate — your gym workout tracker bot. 💪\n\n"
        "You can just tell me about a set in your own words, like:\n"
        "\"bench press 80kg for 8 reps, 3 sets\"\n"
        "\"did squats, 100 for 5\"\n\n"
        "Or don't bother remembering commands at all — there are permanent buttons at the "
        "bottom of the screen now: 📋 Exercises, 🏆 Leaderboard, and 🌐 Language. "
        "Plus the blue menu button to the left of the text field also opens the full exercise "
        "picker right inside Telegram.\n\n"
        "If you forget the weight, reps, or sets — I'll ask. And if you just add something like "
        "\"one more set\" — I'll know you mean the last exercise and update it.\n\n"
        "You can change the interface language anytime with /language or the 🌐 button. Let's go!"
    ),
    "fr": (
        "Je suis LiftMate — ton bot de suivi d'entraînement. 💪\n\n"
        "Tu peux me décrire ta série librement, par exemple :\n"
        "« développé couché 80kg pour 8 répétitions, 3 séries »\n"
        "« squat 100 pour 5 »\n\n"
        "Pas besoin de retenir les commandes — il y a maintenant des boutons permanents en "
        "bas de l'écran : 📋 Exercices, 🏆 Classement, et 🌐 Langue. Le "
        "bouton menu bleu à gauche du champ de texte ouvre aussi l'interface complète des "
        "exercices dans Telegram.\n\n"
        "Si tu oublies le poids, les répétitions ou les séries, je te les demanderai. Et si tu "
        "ajoutes juste « encore une série », je comprendrai que ça concerne le dernier exercice.\n\n"
        "Tu peux changer la langue à tout moment avec /language ou le bouton 🌐. Allons-y !"
    ),
}


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


def language_confirmed_text(language: str) -> str:
    """Подтверждение того, что язык интерфейса сохранён."""
    return _localized(_LANGUAGE_CONFIRMED_TEXT, language)


def welcome_text(language: str) -> str:
    """Приветственный текст /start на выбранном языке пользователя."""
    return _localized(_WELCOME_TEXT, language)


def keyboard_hint_text(language: str) -> str:
    """Короткая подпись при обновлении подписей постоянной клавиатуры (после смены языка)."""
    return _localized(_KEYBOARD_HINT_TEXT, language)


def get_commands(language: str) -> list:
    """Список команд бота (BotCommand) для нативного меню Telegram на заданном языке."""
    return _BOT_COMMANDS[pick_language(language)]


def build_main_reply_keyboard(language: str) -> ReplyKeyboardMarkup:
    """
    Постоянная клавиатура внизу экрана — кнопки-алиасы для /exercises, /leaderboard
    и /language. resize_keyboard=True, чтобы не занимала лишнее место на экране.
    """
    lang = pick_language(language)
    buttons = [KeyboardButton(text=_REPLY_BUTTON_LABELS[action][lang]) for action in ("exercises", "leaderboard", "language")]
    return ReplyKeyboardMarkup(keyboard=[buttons], resize_keyboard=True)


def match_reply_button(text: str) -> Optional[str]:
    """
    Возвращает "exercises"/"leaderboard"/"language", если text совпадает с подписью
    одной из кнопок постоянной клавиатуры (на любом из трёх языков), иначе None.
    """
    for action, labels in _REPLY_BUTTON_LABELS.items():
        if text in labels.values():
            return action
    return None


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
