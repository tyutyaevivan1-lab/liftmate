"""
Данные о популярных упражнениях для inline-меню, сгруппированные по категориям.

Каждое упражнение хранит название на русском, английском и французском —
для отображения кнопки на языке пользователя. В базе данных упражнение всегда
сохраняется под английским названием (см. get_canonical_exercise_name) — это
единый ключ, чтобы прогресс по упражнению не терялся при смене языка интерфейса.
"""

EXERCISE_CATEGORIES = {
    "chest": {
        "name": {"ru": "Грудь", "en": "Chest", "fr": "Poitrine"},
        "exercises": [
            {"key": "bench_press", "ru": "жим лёжа", "en": "bench press", "fr": "développé couché"},
            {"key": "dumbbell_press", "ru": "жим гантелей", "en": "dumbbell press", "fr": "développé couché haltères"},
            {"key": "dumbbell_flyes", "ru": "разводка гантелей", "en": "dumbbell flyes", "fr": "écarté couché haltères"},
            {"key": "machine_chest_press", "ru": "жим в тренажёре", "en": "machine chest press", "fr": "développé à la machine"},
        ],
    },
    "back": {
        "name": {"ru": "Спина", "en": "Back", "fr": "Dos"},
        "exercises": [
            {"key": "barbell_row", "ru": "тяга штанги в наклоне", "en": "bent-over barbell row", "fr": "rowing barre buste penché"},
            {"key": "lat_pulldown", "ru": "тяга блока", "en": "lat pulldown", "fr": "tirage vertical"},
            {"key": "one_arm_dumbbell_row", "ru": "тяга гантели одной рукой", "en": "one-arm dumbbell row", "fr": "rowing haltère à un bras"},
            {"key": "deadlift", "ru": "становая тяга", "en": "deadlift", "fr": "soulevé de terre"},
        ],
    },
    "legs": {
        "name": {"ru": "Ноги", "en": "Legs", "fr": "Jambes"},
        "exercises": [
            {"key": "barbell_squat", "ru": "присед со штангой", "en": "barbell squat", "fr": "squat à la barre"},
            {"key": "leg_press", "ru": "жим ногами", "en": "leg press", "fr": "presse à cuisses"},
            {"key": "lunges", "ru": "выпады", "en": "lunges", "fr": "fentes"},
            {"key": "romanian_deadlift", "ru": "румынская тяга", "en": "romanian deadlift", "fr": "soulevé de terre roumain"},
        ],
    },
    "shoulders": {
        "name": {"ru": "Плечи", "en": "Shoulders", "fr": "Épaules"},
        "exercises": [
            {"key": "standing_barbell_press", "ru": "жим штанги стоя", "en": "standing barbell press", "fr": "développé militaire debout"},
            {"key": "seated_dumbbell_press", "ru": "жим гантелей сидя", "en": "seated dumbbell press", "fr": "développé haltères assis"},
            {"key": "lateral_raises", "ru": "махи гантелями в стороны", "en": "lateral raises", "fr": "élévations latérales"},
        ],
    },
    "biceps": {
        "name": {"ru": "Бицепс", "en": "Biceps", "fr": "Biceps"},
        "exercises": [
            {"key": "barbell_curl", "ru": "подъём штанги на бицепс", "en": "barbell curl", "fr": "curl à la barre"},
            {"key": "dumbbell_curl", "ru": "подъём гантелей на бицепс", "en": "dumbbell curl", "fr": "curl haltères"},
            {"key": "hammer_curl", "ru": "молотки", "en": "hammer curl", "fr": "curl marteau"},
        ],
    },
    "triceps": {
        "name": {"ru": "Трицепс", "en": "Triceps", "fr": "Triceps"},
        "exercises": [
            {"key": "skull_crushers", "ru": "французский жим", "en": "skull crushers", "fr": "extension triceps à la barre"},
            {"key": "cable_pushdown", "ru": "разгибания на блоке", "en": "cable pushdown", "fr": "extension à la poulie"},
            {"key": "dips", "ru": "отжимания на брусьях", "en": "dips", "fr": "dips"},
        ],
    },
}


def pick_language(language: str) -> str:
    """Приводит код/название языка к одному из поддерживаемых ключей меню (ru/en/fr), иначе en."""
    lang = (language or "en").strip().lower()
    if lang.startswith("ru"):
        return "ru"
    if lang.startswith("fr"):
        return "fr"
    return "en"


def get_category_name(category_key: str, language: str) -> str:
    """Возвращает локализованное название категории для кнопки/заголовка."""
    return EXERCISE_CATEGORIES[category_key]["name"][pick_language(language)]


def get_exercise_display_name(exercise: dict, language: str) -> str:
    """Возвращает локализованное название упражнения для отображения в кнопке."""
    return exercise[pick_language(language)]


def get_canonical_exercise_name(exercise: dict) -> str:
    """Английское название — единый ключ для хранения в базе данных."""
    return exercise["en"]


def find_exercise(category_key: str, exercise_key: str) -> dict:
    """Находит упражнение по ключу категории и ключу упражнения."""
    for exercise in EXERCISE_CATEGORIES[category_key]["exercises"]:
        if exercise["key"] == exercise_key:
            return exercise
    raise KeyError(f"Упражнение {exercise_key!r} не найдено в категории {category_key!r}")
