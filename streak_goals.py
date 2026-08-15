"""
Система "целевого" streak — трекинг тренировок по личному расписанию пользователя
(конкретные дни недели), с системой званий по общему числу записанных тренировок.

ВАЖНО: это НЕ то же самое, что user_stats.current_streak/longest_streak в database.py —
та серия считает просто подряд идущие календарные дни с хотя бы одной тренировкой и
обслуживает публичный лидерборд (см. leaderboard.py, /leaderboard) — она одинаково
"справедлива" для всех, независимо от того, сколько раз в неделю кто планирует
тренироваться. Streak из этого модуля персональный: у пользователя, который тренируется
2 раза в неделю по расписанию, streak не должен ломаться в дни между тренировками, а у
того, кто тренируется 5 раз в неделю — должен. Сравнивать эти два streak напрямую между
пользователями было бы нечестно, поэтому они хранятся и считаются отдельно.

Ключевое архитектурное решение: current_streak/longest_streak НЕ хранятся как отдельный
счётчик, который нужно инкрементировать/сбрасывать при каждой записи тренировки (в отличие
от user_stats). Вместо этого compute_streak() считает их ЗАНОВО каждый раз из настоящего
списка дат тренировок (database.get_workout_dates) и сохранённого расписания
(database.get_streak_goal). Это устраняет целый класс багов (пропущенные обновления,
рассинхрон при бэкфилле старых данных и т.п.) и одновременно исключает накрутку по
конструкции — нет действия, которое двигает streak в обход реальной записи в workouts.
"""

from datetime import date, timedelta
from typing import Optional

from exercises_data import pick_language

# Отправная точка для КОЛИЧЕСТВА целевых дней, если у пользователя уже есть days_per_week
# из сплит-профиля (program.FREQUENCY_TO_DAYS_PER_WEEK) — сознательно НЕ те же самые дни,
# что в сплите (см. docstring модуля и обсуждение с пользователем), просто разумное число
# дней в неделю как отправная точка; пользователь может изменить это позже.
_DEFAULT_TARGET_WEEKDAYS_BY_DAYS_PER_WEEK = {
    1: [1],  # понедельник
    3: [1, 3, 5],  # пн/ср/пт
    4: [1, 2, 4, 5],  # пн/вт/чт/пт
    5: [1, 2, 3, 4, 5],  # пн-пт
}
# Нет вообще никакого профиля/сплита — нейтральная отправная точка (3 дня, через день)
_DEFAULT_TARGET_WEEKDAYS_FALLBACK = [1, 3, 5]


def default_target_weekdays(days_per_week: Optional[int]) -> list:
    """Разумные дни недели по умолчанию — см. комментарий у _DEFAULT_TARGET_WEEKDAYS_BY_DAYS_PER_WEEK."""
    return _DEFAULT_TARGET_WEEKDAYS_BY_DAYS_PER_WEEK.get(days_per_week, _DEFAULT_TARGET_WEEKDAYS_FALLBACK)


def _scheduled_dates_between(target_weekdays: set, start: date, end: date) -> list:
    """Все календарные даты в [start, end] включительно, чей ISO-день недели входит в target_weekdays."""
    if start > end:
        return []
    total_days = (end - start).days
    return [
        start + timedelta(days=offset)
        for offset in range(total_days + 1)
        if (start + timedelta(days=offset)).isoweekday() in target_weekdays
    ]


def compute_streak(target_weekdays: set, workout_dates: set, schedule_set_at: date, today: date) -> dict:
    """
    Считает current_streak/longest_streak с нуля по реальным датам тренировок.

    current_streak — число подряд идущих целевых дней (от schedule_set_at до today
    включительно), для которых была хотя бы одна тренировка, считая от самого недавнего
    оценённого дня назад до первого пропуска. Целевой день, приходящийся на СЕГОДНЯ,
    засчитывается сразу, если тренировка уже записана, но НЕ считается пропуском, пока
    сегодняшний день не закончился (т.е. пока не наступит завтра) — иначе streak ломался
    бы посреди дня ещё до того, как у пользователя был шанс потренироваться.

    longest_streak — максимальная длина такой последовательности за всю историю с
    schedule_set_at по today.
    """
    scheduled_dates = _scheduled_dates_between(target_weekdays, schedule_set_at, today)
    evaluable_dates = [d for d in scheduled_dates if d < today or d in workout_dates]

    longest_streak = 0
    running = 0
    for d in evaluable_dates:
        if d in workout_dates:
            running += 1
            longest_streak = max(longest_streak, running)
        else:
            running = 0

    return {
        "current_streak": running,
        "longest_streak": longest_streak,
        "target_weekdays": sorted(target_weekdays),
    }


# Пороги званий по числу УНИКАЛЬНЫХ ДНЕЙ, когда пользователь тренировался хотя бы раз
# (len(database.get_workout_dates(...))) — НЕ по числу отдельных записей упражнений и
# НЕ по длине streak. Раньше здесь ошибочно считались записи, что уравнивало 1 день из
# 9 подходов с 9 разными тренировочными днями. От большего порога к меньшему — первое
# совпадение побеждает.
_RANK_THRESHOLDS = [
    (30, "🏆", {"ru": "Легенда зала", "en": "Gym Legend", "fr": "Légende de la salle"}),
    (15, "⚙️", {"ru": "Машина", "en": "Machine", "fr": "Machine"}),
    (7, "🔥", {"ru": "Разогнался", "en": "Picking Up Speed", "fr": "En pleine accélération"}),
    (3, "💪", {"ru": "Втянулся", "en": "Getting Into It", "fr": "Sur la bonne voie"}),
    (0, "🌱", {"ru": "Новичок", "en": "Beginner", "fr": "Débutant"}),
]


def get_rank_title(total_workout_days: int, language: str) -> str:
    """
    Звание пользователя ("<название> <эмодзи>") по числу уникальных дней с тренировками.
    Последний порог в _RANK_THRESHOLDS — 0, так что цикл всегда находит совпадение.
    """
    lang = pick_language(language)
    for threshold, emoji, names in _RANK_THRESHOLDS:
        if total_workout_days >= threshold:
            return f"{names[lang]} {emoji}"
