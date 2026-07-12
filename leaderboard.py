"""
Глобальный лидерборд по сериям тренировок (ЭТАП 1 — бесплатный, по streak).

Задел на будущее, чтобы не мешать следующим этапам архитектурой:
- database.get_leaderboard_top()/get_user_rank() уже принимают опциональный user_ids —
  это всё, что понадобится дружеским лидербордам (передать id участников группы),
  без изменения самих функций.
- build_leaderboard_message() принимает board_type; premium-лидерборды по абсолютному
  весу и % прогресса добавятся сюда отдельными ветками (с проверкой user_stats.is_premium
  на стороне вызывающего кода в handlers.py), не трогая уже готовую ветку "streak_global".
"""

from typing import Optional

from exercises_data import pick_language
from utils import pluralize_days

_TITLE = {
    "ru": "🏆 Топ по сериям тренировок:",
    "en": "🏆 Workout streak leaderboard:",
    "fr": "🏆 Classement des séries d'entraînement :",
}

_YOUR_RANK_TEXT = {
    "ru": "Ты на {rank} месте с серией {streak} {days_word}. Продолжай в том же духе!",
    "en": "You're #{rank} with a {streak}-day streak. Keep it up!",
    "fr": "Tu es {rank}ᵉ avec une série de {streak} {days_word}. Continue comme ça !",
}

_NO_STREAK_YET_TEXT = {
    "ru": "У тебя пока нет серии — запиши тренировку, чтобы попасть в рейтинг!",
    "en": "You don't have a streak yet — log a workout to join the leaderboard!",
    "fr": "Tu n'as pas encore de série — enregistre un entraînement pour rejoindre le classement !",
}

_EMPTY_BOARD_TEXT = {
    "ru": "Пока в рейтинге никого нет — стань первым!",
    "en": "No one's on the leaderboard yet — be the first!",
    "fr": "Personne dans le classement pour l'instant — sois le premier !",
}


def pseudonym_for(user_id: int) -> str:
    """
    Анонимный, но стабильный псевдоним пользователя для лидерборда: последние 4 цифры
    user_id. Ничего не хранится отдельно — это чистая функция от user_id, поэтому
    псевдоним всегда одинаков при каждом показе для одного и того же пользователя.

    Компромисс: у разных пользователей с совпадающими последними 4 цифрами id псевдоним
    совпадёт — для анонимного топа это приемлемо.
    """
    return f"Атлет #{user_id % 10000:04d}"


def _days_word(count: int, language: str) -> str:
    lang = pick_language(language)
    if lang == "ru":
        return pluralize_days(count)
    if lang == "fr":
        return "jour" if count == 1 else "jours"
    return "day" if count == 1 else "days"


def _localized(mapping: dict, language: str, **kwargs) -> str:
    text = mapping[pick_language(language)]
    return text.format(**kwargs) if kwargs else text


def build_leaderboard_message(
    top_entries: list,
    user_rank_info: Optional[dict],
    language: str,
    board_type: str = "streak_global",
) -> str:
    """
    Собирает текст сообщения лидерборда: заголовок, нумерованный топ (псевдоним + серия,
    🔥 у первого места) и отдельной строкой — место текущего пользователя, даже если он
    не входит в показанный топ.

    board_type сейчас поддерживает только "streak_global" (бесплатный глобальный
    лидерборд по сериям, ЭТАП 1).
    """
    if board_type != "streak_global":
        raise NotImplementedError(f"Тип лидерборда {board_type!r} пока не реализован")

    lines = [_localized(_TITLE, language)]

    if not top_entries:
        lines.append(_localized(_EMPTY_BOARD_TEXT, language))
    else:
        for position, entry in enumerate(top_entries, start=1):
            streak = entry["current_streak"]
            suffix = " 🔥" if position == 1 else ""
            lines.append(
                f"{position}. {pseudonym_for(entry['user_id'])} — {streak} {_days_word(streak, language)}{suffix}"
            )

    lines.append("")

    if user_rank_info is None:
        lines.append(_localized(_NO_STREAK_YET_TEXT, language))
    else:
        lines.append(
            _localized(
                _YOUR_RANK_TEXT,
                language,
                rank=user_rank_info["rank"],
                streak=user_rank_info["current_streak"],
                days_word=_days_word(user_rank_info["current_streak"], language),
            )
        )

    return "\n".join(lines)
