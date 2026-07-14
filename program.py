"""
Генерация программы тренировки через GPT-4o-mini, тремя способами:
1) "по цели" (набрать массу / похудеть / выносливость) — один день, generate_workout_program;
2) "на основе истории тренировок" (см. database.get_recent_distinct_exercises) — один день,
   тот же generate_workout_program;
3) "Сплит на неделю" — несколько дней сразу, по сплиту (full body/upper-lower/PPL/bro split),
   см. generate_split_program и get_split_options — выбор реального сплита (а не
   зафиксированного) доступен только premium (get_split_options(is_premium=...)).

Учитывает профиль пользователя (см. database.get_fitness_profile: опыт, оборудование,
ограничения, а для сплит-режима — ещё и days_per_week/chosen_split) — заполняется через
мини-опрос (см. handlers.py, states.ProfileStates) перед первой генерацией.

Программа определяет только УПРАЖНЕНИЯ, КОЛИЧЕСТВО ПОДХОДОВ/ПОВТОРЕНИЙ и краткое "почему"
для каждого упражнения — конкретный вес пользователь вводит сам при выполнении.

GPT возвращает структурированный JSON (текст для Telegram + список упражнений отдельно —
"exercises" для одного дня, "days" со списком дней для сплита), чтобы одна и та же
программа могла быть показана и в чате, и в виде карточек в Web App (см. api.py:
GET /api/user/{user_id}/program/latest, webapp/app.js).
"""

import json
import logging
from typing import Optional

from openai import AsyncOpenAI

from config import OPENAI_API_KEY
from database import get_fitness_profile, get_recent_distinct_exercises
from exercises_data import pick_language
from utils import pluralize_sets

logger = logging.getLogger(__name__)

client = AsyncOpenAI(api_key=OPENAI_API_KEY)

GOALS = ("bulk", "cut", "endurance")

# Общая часть промпта (переиспользуется во всех трёх способах составления программы):
# как учитывать профиль пользователя. Схема JSON-ответа у каждого способа своя
# (single-day "text"+"exercises" ниже, vs "day_title"+"exercises" у сплит-дня) —
# поэтому вынесена отдельно от инструкций по формату ответа.
_PROFILE_INSTRUCTIONS = """
Учти профиль пользователя (поле "profile" во входном JSON):
- experience_months — стаж тренировок в месяцах (null, если неизвестен — тогда считай пользователя тренирующимся среднего уровня). Меньше 3 месяцев — упрощай технику, избегай сложных многосуставных/травмоопасных упражнений без уверенной техники, меньше объём. 3-12 месяцев — средний уровень. Больше 12 месяцев — можно больше объёма и сложности.
- equipment_type — что доступно: "free_weights" (только гантели/штанга), "machines" (только тренажёры), "full_gym" (полный зал, доступно всё), "home" (дом/минимум инвентаря — используй упражнения с собственным весом, эспандеры, максимум пару лёгких предметов). Подбирай упражнения СТРОГО из того, что реально доступно с этим оборудованием.
- equipment_details — уточнение пользователя своими словами о конкретном инвентаре (может быть null) — учти, если релевантно.
- limitations — травмы/ограничения (может быть null, если их нет) — избегай упражнений, небезопасных при этом ограничении, и при необходимости выбирай более щадящую альтернативу.
"""

_SINGLE_DAY_OUTPUT_INSTRUCTIONS = """
Верни ТОЛЬКО валидный JSON без пояснений и markdown, строго такой структуры:
{
  "text": "полный текст сообщения пользователю НА ЯЗЫКЕ language, без markdown-разметки — тёплая вводная фраза, затем пронумерованный список из 4-6 упражнений вида 'Название — X подхода(ов) × Y-Z повторений — краткое объяснение почему', и в конце короткая бодрая фраза-напутствие с эмодзи 💪",
  "exercises": [
    {"name": "название упражнения", "sets": число_подходов, "reps": "диапазон повторений строкой, например '8-10' или 'до отказа'", "why": "одна короткая фраза — почему это упражнение в программе"}
  ]
}

ВАЖНО:
- НЕ указывай конкретный вес — только количество подходов и повторений (или "до отказа"), пользователь сам вводит вес при выполнении.
- Массив "exercises" должен ТОЧНО соответствовать пронумерованному списку в "text": то же количество упражнений, в том же порядке, те же значения sets/reps, и то же "why" (в "text" оно просто вписано в предложение, а не отдельным полем).
- Все текстовые поля ("text", "name", "why") — на языке "language" (пиши как носитель этого языка, не переводи дословно с русского).
"""

_PROFILE_AND_OUTPUT_INSTRUCTIONS = _PROFILE_INSTRUCTIONS + _SINGLE_DAY_OUTPUT_INSTRUCTIONS

SYSTEM_PROMPT_BY_GOAL = """Ты — LiftMate, бот-трекер тренировок, который общается как опытный, дружелюбный тренер и близкий друг по залу: тепло, неформально, с поддержкой, без наигранности.

Составь ПРОСТУЮ программу тренировки НА ОДИН ДЕНЬ под конкретную цель пользователя.

На вход придёт JSON:
- goal — цель: "bulk" (набрать мышечную массу), "cut" (похудеть/жиросжигание), "endurance" (выносливость)
- profile — профиль пользователя (см. ниже)
- language — язык ответа

Правила подбора упражнений и параметров под цель:
- "bulk": 4-6 базовых и вспомогательных упражнений на одну логичную группу мышц дня (например, грудь+трицепс, или спина+бицепс, или ноги — выбери сам одну группу), 3-4 подхода, 8-12 повторений — умеренный объём под рост мышц.
- "cut": 5-6 упражнений в чуть более высоком темпе (можно включить функциональные/многосуставные элементы), 3 подхода, 12-15 повторений — под жиросжигание и высокий метаболический расход.
- "endurance": 4-5 упражнений, включая многоповторные элементы, 2-3 подхода, 15-20 повторений или "до отказа" — под мышечную выносливость.
""" + _PROFILE_AND_OUTPUT_INSTRUCTIONS


SYSTEM_PROMPT_BY_HISTORY = """Ты — LiftMate, бот-трекер тренировок, который общается как опытный, дружелюбный тренер и близкий друг по залу: тепло, неформально, с поддержкой, без наигранности.

Составь ПРОСТУЮ программу тренировки НА ОДИН ДЕНЬ, которая логично ПРОДОЛЖАЕТ историю тренировок пользователя.

На вход придёт JSON:
- recent_exercises — список последних РАЗНЫХ упражнений пользователя, каждое с последним весом/повторениями/подходами и датой (от самого недавнего к более давнему); может быть пустым списком
- profile — профиль пользователя (см. ниже)
- language — язык ответа

Как выбрать упражнения:
- Посмотри, какие группы мышц пользователь тренировал в последнее время (recent_exercises), и предложи логичное продолжение — по стандартной сплит-логике (например, если последними были упражнения на грудь/трицепс — сегодня предложи спину/бицепс или ноги; если давно не было чего-то — можно и повторить ту же группу).
- Учитывай его текущие веса из recent_exercises, чтобы понимать его уровень, но НЕ указывай вес в самой программе (только подходы/повторения) — пользователь введёт вес сам при выполнении.
- Если recent_exercises — пустой список, у пользователя ещё нет истории: предложи сбалансированную стартовую программу на всё тело (4-6 упражнений, 3 подхода, 8-12 повторений) и мягко упомяни в вводной фразе, что это стартовый вариант, а дальше программа будет подстраиваться под его историю.
""" + _PROFILE_AND_OUTPUT_INSTRUCTIONS


_FALLBACK_PROGRAM = {
    "ru": {
        "text": (
            "Не получилось составить программу под тебя, но вот надёжная база на сегодня, бро:\n\n"
            "1. Жим лёжа — 4 подхода × 8-10 повторений — база для силы и массы груди и трицепса\n"
            "2. Тяга штанги в наклоне — 4 подхода × 8-10 повторений — главное упражнение для толщины спины\n"
            "3. Приседания — 3 подхода × 10-12 повторений — основа для силы и массы ног\n"
            "4. Жим гантелей сидя — 3 подхода × 10-12 повторений — развивает плечи и стабилизаторы\n"
            "5. Подтягивания — 3 подхода × до отказа — классика для спины и бицепса\n\n"
            "Погнали! 💪"
        ),
        "exercises": [
            {"name": "Жим лёжа", "sets": 4, "reps": "8-10", "why": "База для силы и массы груди и трицепса"},
            {"name": "Тяга штанги в наклоне", "sets": 4, "reps": "8-10", "why": "Главное упражнение для толщины спины"},
            {"name": "Приседания", "sets": 3, "reps": "10-12", "why": "Основа для силы и массы ног"},
            {"name": "Жим гантелей сидя", "sets": 3, "reps": "10-12", "why": "Развивает плечи и стабилизаторы"},
            {"name": "Подтягивания", "sets": 3, "reps": "до отказа", "why": "Классика для спины и бицепса"},
        ],
    },
    "en": {
        "text": (
            "Couldn't put together a personalized plan, but here's a solid go-to for today, bro:\n\n"
            "1. Bench press — 4 sets × 8-10 reps — the staple for chest and triceps strength/size\n"
            "2. Bent-over row — 4 sets × 8-10 reps — main move for back thickness\n"
            "3. Squats — 3 sets × 10-12 reps — foundation for leg strength and size\n"
            "4. Seated dumbbell press — 3 sets × 10-12 reps — builds shoulders and stabilizers\n"
            "5. Pull-ups — 3 sets × to failure — a classic for back and biceps\n\n"
            "Let's go! 💪"
        ),
        "exercises": [
            {"name": "Bench press", "sets": 4, "reps": "8-10", "why": "The staple for chest and triceps strength/size"},
            {"name": "Bent-over row", "sets": 4, "reps": "8-10", "why": "Main move for back thickness"},
            {"name": "Squats", "sets": 3, "reps": "10-12", "why": "Foundation for leg strength and size"},
            {"name": "Seated dumbbell press", "sets": 3, "reps": "10-12", "why": "Builds shoulders and stabilizers"},
            {"name": "Pull-ups", "sets": 3, "reps": "to failure", "why": "A classic for back and biceps"},
        ],
    },
    "fr": {
        "text": (
            "Impossible de préparer un programme personnalisé, mais voici une base solide pour aujourd'hui, champion :\n\n"
            "1. Développé couché — 4 séries × 8-10 répétitions — la base pour la force et le volume des pectoraux et triceps\n"
            "2. Rowing barre buste penché — 4 séries × 8-10 répétitions — l'exercice clé pour l'épaisseur du dos\n"
            "3. Squats — 3 séries × 10-12 répétitions — la base pour la force et le volume des jambes\n"
            "4. Développé haltères assis — 3 séries × 10-12 répétitions — développe les épaules et les stabilisateurs\n"
            "5. Tractions — 3 séries × jusqu'à l'échec — un classique pour le dos et les biceps\n\n"
            "Allons-y ! 💪"
        ),
        "exercises": [
            {"name": "Développé couché", "sets": 4, "reps": "8-10", "why": "La base pour la force et le volume des pectoraux et triceps"},
            {"name": "Rowing barre buste penché", "sets": 4, "reps": "8-10", "why": "L'exercice clé pour l'épaisseur du dos"},
            {"name": "Squats", "sets": 3, "reps": "10-12", "why": "La base pour la force et le volume des jambes"},
            {"name": "Développé haltères assis", "sets": 3, "reps": "10-12", "why": "Développe les épaules et les stabilisateurs"},
            {"name": "Tractions", "sets": 3, "reps": "jusqu'à l'échec", "why": "Un classique pour le dos et les biceps"},
        ],
    },
}


def _fallback_program(language: str) -> dict:
    """Запасной шаблонный вариант программы (text + exercises) на случай ошибки/некорректного ответа OpenAI."""
    return _FALLBACK_PROGRAM[pick_language(language)]


def _profile_payload(profile: Optional[dict]) -> dict:
    """Приводит профиль из БД (или его отсутствие) к payload для GPT — с явными null для неизвестных полей."""
    if profile is None:
        return {"experience_months": None, "equipment_type": None, "equipment_details": None, "limitations": None}
    return {
        "experience_months": profile.get("experience_months"),
        "equipment_type": profile.get("equipment_type"),
        "equipment_details": profile.get("equipment_details"),
        "limitations": profile.get("limitations"),
    }


def _parse_program_response(raw_content: str, language: str) -> dict:
    """
    Разбирает JSON-ответ GPT в {"text": str, "exercises": list}. При некорректной структуре
    (не тот формат, пустой список упражнений и т.п.) откатывается на запасной шаблон —
    лучше стабильная дженерик-программа, чем сломанный teaser-экран в Web App.
    """
    data = json.loads(raw_content)
    text = data.get("text")
    exercises = data.get("exercises")

    if not text or not isinstance(exercises, list) or not exercises:
        raise ValueError("GPT вернул программу без текста или без списка упражнений")

    normalized_exercises = [
        {
            "name": str(item["name"]).strip(),
            "sets": int(item["sets"]),
            "reps": str(item["reps"]).strip(),
            "why": str(item["why"]).strip(),
        }
        for item in exercises
    ]
    return {"text": text.strip(), "exercises": normalized_exercises}


async def _call_gpt_for_program(system_prompt: str, payload: dict, language: str) -> dict:
    """Общий вызов OpenAI для обоих режимов — отличаются только system_prompt и payload."""
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0.7,
            response_format={"type": "json_object"},
        )
        return _parse_program_response(response.choices[0].message.content, language)
    except Exception:
        logger.exception("Не удалось сгенерировать программу тренировки через OpenAI, используем запасной вариант")
        return _fallback_program(language)


async def _ensure_premium_if_needed(user_id: int, num_days: int) -> None:
    """
    Заглушка для этой (single-day, "по цели"/"история") генерации — она всегда на 1 день,
    поэтому premium не требуется и проверка всегда проходит без ограничений. Многодневная
    генерация реализована ОТДЕЛЬНОЙ функцией generate_split_program (см. ниже), где реальный
    выбор сплита уже ограничен premium через get_split_options(is_premium=...).
    """
    return


async def generate_workout_program(
    user_id: int,
    mode: str,
    language: str,
    goal: Optional[str] = None,
    num_days: int = 1,
) -> dict:
    """
    Генерирует программу тренировки. Возвращает {"text": str, "exercises": list[dict]}:
    - "text" — готовое сообщение для Telegram (включает нумерованный список с "почему");
    - "exercises" — та же программа в структурированном виде: [{"name","sets","reps","why"}, ...],
      для сохранения (database.save_user_program) и для teaser-экрана в Web App.

    mode: "goal" (требует goal из GOALS) | "history" (использует последние разные
    упражнения пользователя, см. database.get_recent_distinct_exercises; если истории
    нет — GPT сам предлагает стартовую программу на всё тело).

    Автоматически подтягивает сохранённый профиль пользователя (database.get_fitness_profile)
    и передаёт его GPT для персонализации — опыт, оборудование, ограничения.

    num_days: единственное, что здесь поддерживается — 1 (эта функция всегда возвращает
    один день). Многодневная "Сплит на неделю" программа — отдельная функция
    generate_split_program, см. ниже.
    """
    if num_days != 1:
        raise NotImplementedError(
            "Многодневные программы — будущая premium-функция, пока поддерживается только num_days=1"
        )

    await _ensure_premium_if_needed(user_id, num_days)

    profile = await get_fitness_profile(user_id)
    profile_payload = _profile_payload(profile)

    if mode == "goal":
        if goal not in GOALS:
            raise ValueError(f"Неизвестная цель программы: {goal!r}")
        payload = {"goal": goal, "profile": profile_payload, "language": language}
        return await _call_gpt_for_program(SYSTEM_PROMPT_BY_GOAL, payload, language)

    if mode == "history":
        recent = await get_recent_distinct_exercises(user_id, limit=8)
        payload = {
            "recent_exercises": [
                {
                    "exercise_name": row["exercise_name"],
                    "weight": row["weight"],
                    "reps": row["reps"],
                    "sets": row["sets"],
                    "date": row["created_at"].split("T")[0],
                }
                for row in recent
            ],
            "profile": profile_payload,
            "language": language,
        }
        return await _call_gpt_for_program(SYSTEM_PROMPT_BY_HISTORY, payload, language)

    raise ValueError(f"Неизвестный режим составления программы: {mode!r}")


# ---------------------------------------------------------------------------
# "Сплит на неделю" — третий способ составления программы (см. handlers.py:
# _start_split_flow), рядом с "по цели"/"историей" выше. Профиль хранит
# days_per_week/chosen_split (см. database.save_fitness_profile/update_split_preference),
# а сама программа генерируется ПО ОДНОМУ ДНЮ за вызов GPT и собирается в неделю —
# так надёжнее (нет повторов между днями, нет рассинхрона объёма), чем один большой
# промпт на всю неделю разом.
# ---------------------------------------------------------------------------

# Частота тренировок в неделю -> нижняя граница диапазона (хранится в профиле как int)
FREQUENCY_TO_DAYS_PER_WEEK = {"1-2": 1, "3": 3, "4": 4, "5-6": 5}

SPLIT_GOALS = ("build_muscle", "lose_weight", "strength")

# Группы мышц по дням для каждого типа сплита (на английском — это внутренний вход
# для GPT-промпта, а не то, что видит пользователь; локализованное название дня
# генерирует сам GPT в поле "day_title", см. SYSTEM_PROMPT_SPLIT_DAY)
SPLIT_DAY_FOCUS = {
    "full_body": [
        "Full body — chest, back, legs, shoulders, arms, core",
    ],
    "upper_lower": [
        "Upper body — chest, back, shoulders, arms",
        "Lower body — quads, hamstrings, glutes, calves",
    ],
    "upper_lower_x2": [
        "Upper body — chest, back, shoulders, arms",
        "Lower body — quads, hamstrings, glutes, calves",
        "Upper body — chest, back, shoulders, arms (variation)",
        "Lower body — quads, hamstrings, glutes, calves (variation)",
    ],
    "ppl_single": [
        "Push — chest, shoulders, triceps",
        "Pull — back, biceps",
        "Legs — quads, hamstrings, glutes, calves",
    ],
    "ppl_double": [
        "Push — chest, shoulders, triceps",
        "Pull — back, biceps",
        "Legs — quads, hamstrings, glutes, calves",
        "Push — chest, shoulders, triceps (variation)",
        "Pull — back, biceps (variation)",
        "Legs — quads, hamstrings, glutes, calves (variation)",
    ],
    "bro_split": [
        "Chest only",
        "Back only",
        "Shoulders only",
        "Arms — biceps and triceps",
        "Legs — quads, hamstrings, glutes, calves",
    ],
}

# Подписи типов сплита для inline-кнопок выбора и для апселл-сообщения (locked-вариант)
_SPLIT_LABELS = {
    "full_body": {"ru": "Всё тело за раз", "en": "Full body", "fr": "Corps entier"},
    "upper_lower": {"ru": "Верх/низ", "en": "Upper/Lower", "fr": "Haut/Bas"},
    "upper_lower_x2": {
        "ru": "Верх/низ (2 цикла)",
        "en": "Upper/Lower (2x)",
        "fr": "Haut/Bas (2 cycles)",
    },
    "ppl_single": {
        "ru": "Push/Pull/Legs",
        "en": "Push/Pull/Legs",
        "fr": "Push/Pull/Legs",
    },
    "ppl_double": {
        "ru": "Push/Pull/Legs (2 цикла)",
        "en": "Push/Pull/Legs (2x)",
        "fr": "Push/Pull/Legs (2 cycles)",
    },
    "bro_split": {
        "ru": "Bro Split (по группе в день)",
        "en": "Bro Split (one muscle group per day)",
        "fr": "Bro Split (un groupe par jour)",
    },
}


def split_label(split_key: str, language: str) -> str:
    """Локализованное название типа сплита — для кнопок выбора и апселл-сообщения."""
    return _SPLIT_LABELS[split_key][pick_language(language)]


def get_split_options(days_per_week: int, experience_months: Optional[int], is_premium: bool) -> dict:
    """
    Определяет, какой сплит доступен пользователю по частоте тренировок и стажу, и нужно
    ли вообще показывать выбор (см. бриф "Логика выбора сплита"):

    - При низкой частоте (<=3 раз/нед) и стаже <12 мес — full body без вариантов: сплиты
      на этой частоте дают меньше стимула на группу мышц в неделю, чем full body,
      это не искусственное ограничение, а более эффективный вариант.
    - При 4 раза/нед — upper/lower безальтернативно.
    - При 3 раза/нед и стаже >=12 мес, или 5+ раз/нед — есть из чего выбирать, но
      реальный выбор даём только premium; free видит варианты, но зафиксирован на первом.

    Возвращает {"fixed": str|None, "choice_shown": bool, "locked": bool, "options": list|None}.
    "fixed" — сплит, который будет использован, если choice_shown=False, либо если
    locked=True (заблокированный выбор для free — берём options[0]).
    """
    experience_months = experience_months or 0

    if days_per_week <= 3 and experience_months < 12:
        return {"fixed": "full_body", "choice_shown": False, "locked": False, "options": None}

    if days_per_week == 4:
        return {"fixed": "upper_lower", "choice_shown": False, "locked": False, "options": None}

    if days_per_week == 3 and experience_months >= 12:
        options = ["full_body", "ppl_single"]
    elif days_per_week >= 5:
        options = ["ppl_double", "bro_split"] if experience_months >= 36 else ["ppl_double", "upper_lower_x2"]
    else:
        return {"fixed": "full_body", "choice_shown": False, "locked": False, "options": None}

    if not is_premium:
        # Free видит, что выбор есть, но он зафиксирован на первом (наиболее сбалансированном) варианте
        return {"fixed": options[0], "choice_shown": True, "locked": True, "options": options}

    return {"fixed": None, "choice_shown": True, "locked": False, "options": options}


_SPLIT_DAY_OUTPUT_INSTRUCTIONS = """
Верни ТОЛЬКО валидный JSON без пояснений и markdown, строго такой структуры:
{
  "day_title": "короткое название дня с указанием групп мышц, НА ЯЗЫКЕ language (например 'Толкающие: грудь, плечи, трицепс' или 'Push day: chest, shoulders, triceps')",
  "exercises": [
    {"name": "название упражнения на языке language", "sets": число_подходов, "reps": "диапазон повторений строкой, например '8-12' или '3-6'", "why": "одна короткая фраза — почему это упражнение в программе"}
  ]
}

ВАЖНО:
- НЕ указывай конкретный вес — только количество подходов и повторений, пользователь сам вводит вес при выполнении.
- Дай 5-7 упражнений СТРОГО под указанный фокус групп мышц (muscle_focus) — не добавляй упражнения на группы вне фокуса этого дня.
- Порядок упражнений: сначала многосуставные/базовые, потом изоляция.
- Все текстовые поля ("day_title", "name", "why") — на языке "language" (пиши как носитель этого языка, не переводи дословно с русского).
"""

SYSTEM_PROMPT_SPLIT_DAY = """Ты — LiftMate, опытный дружелюбный тренер, который составляет ОДИН день тренировочной программы — часть более крупного сплита на несколько дней в неделе.

На вход придёт JSON:
- muscle_focus — на английском, какие группы мышц сегодня в фокусе (например "Push — chest, shoulders, triceps")
- goal — цель: "build_muscle" (набрать мышечную массу), "lose_weight" (похудеть), "strength" (сила)
- profile — профиль пользователя (см. ниже)
- previous_day_exercises — если это ВТОРОЙ день с тем же фокусом на этой неделе (вариация), список упражнений из первого такого дня; иначе null
- language — язык ответа

Подбери сеты/повторы под цель:
- "build_muscle" → 3-4 подхода × 8-12 повторений
- "lose_weight" → 3 подхода × 12-15 повторений (можешь упомянуть в why, что отдых между подходами короче)
- "strength" → 3-5 подходов × 3-6 повторений на базовых многосуставных движениях

Если previous_day_exercises НЕ null — это уже второй такой день на неделе: обязательно возьми ДРУГИЕ упражнения на те же группы мышц, не повторяя их (например, если был Barbell Bench Press — возьми Dumbbell Press или Incline Press).
""" + _PROFILE_INSTRUCTIONS + _SPLIT_DAY_OUTPUT_INSTRUCTIONS


_FALLBACK_SPLIT_DAY = {
    "ru": {
        "day_title": "Тренировка на всё тело",
        "exercises": [
            {"name": "Приседания", "sets": 3, "reps": "10-12", "why": "Основа для силы и массы ног"},
            {"name": "Жим лёжа", "sets": 3, "reps": "8-10", "why": "База для груди и трицепса"},
            {"name": "Тяга штанги в наклоне", "sets": 3, "reps": "8-10", "why": "Толщина спины"},
            {"name": "Жим гантелей сидя", "sets": 3, "reps": "10-12", "why": "Развивает плечи"},
            {"name": "Планка", "sets": 3, "reps": "30-60 секунд", "why": "Укрепляет кор"},
        ],
    },
    "en": {
        "day_title": "Full body workout",
        "exercises": [
            {"name": "Squats", "sets": 3, "reps": "10-12", "why": "Foundation for leg strength and size"},
            {"name": "Bench press", "sets": 3, "reps": "8-10", "why": "The staple for chest and triceps"},
            {"name": "Bent-over row", "sets": 3, "reps": "8-10", "why": "Back thickness"},
            {"name": "Seated dumbbell press", "sets": 3, "reps": "10-12", "why": "Builds shoulders"},
            {"name": "Plank", "sets": 3, "reps": "30-60 seconds", "why": "Strengthens the core"},
        ],
    },
    "fr": {
        "day_title": "Séance corps entier",
        "exercises": [
            {"name": "Squats", "sets": 3, "reps": "10-12", "why": "La base pour la force des jambes"},
            {"name": "Développé couché", "sets": 3, "reps": "8-10", "why": "La base pour pectoraux et triceps"},
            {"name": "Rowing barre buste penché", "sets": 3, "reps": "8-10", "why": "Épaisseur du dos"},
            {"name": "Développé haltères assis", "sets": 3, "reps": "10-12", "why": "Développe les épaules"},
            {"name": "Planche", "sets": 3, "reps": "30-60 secondes", "why": "Renforce le gainage"},
        ],
    },
}


def _fallback_split_day(language: str) -> dict:
    """Запасной шаблонный день на случай ошибки/некорректного ответа OpenAI."""
    return _FALLBACK_SPLIT_DAY[pick_language(language)]


def _parse_split_day_response(raw_content: str) -> dict:
    """Разбирает JSON-ответ GPT в {"day_title": str, "exercises": list}. См. _parse_program_response."""
    data = json.loads(raw_content)
    day_title = data.get("day_title")
    exercises = data.get("exercises")

    if not day_title or not isinstance(exercises, list) or not exercises:
        raise ValueError("GPT вернул день без названия или без списка упражнений")

    normalized_exercises = [
        {
            "name": str(item["name"]).strip(),
            "sets": int(item["sets"]),
            "reps": str(item["reps"]).strip(),
            "why": str(item["why"]).strip(),
        }
        for item in exercises
    ]
    return {"day_title": day_title.strip(), "exercises": normalized_exercises}


async def _generate_split_day(
    muscle_focus: str,
    goal: str,
    profile_payload: dict,
    language: str,
    previous_day_exercises: Optional[list],
) -> dict:
    """Один вызов GPT — один день сплита. При ошибке откатывается на запасной день."""
    payload = {
        "muscle_focus": muscle_focus,
        "goal": goal,
        "profile": profile_payload,
        "previous_day_exercises": previous_day_exercises,
        "language": language,
    }
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_SPLIT_DAY},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0.7,
            response_format={"type": "json_object"},
        )
        return _parse_split_day_response(response.choices[0].message.content)
    except Exception:
        logger.exception("Не удалось сгенерировать день сплита через OpenAI, используем запасной вариант")
        return _fallback_split_day(language)


def _base_muscle_focus(muscle_focus: str) -> str:
    """Убирает суффикс "(variation)", чтобы сопоставить день-вариацию с его оригиналом."""
    return muscle_focus.replace(" (variation)", "").strip()


_DAY_HEADER = {"ru": "День {n}: {title}", "en": "Day {n}: {title}", "fr": "Jour {n} : {title}"}
_WEEK_INTRO = {
    "ru": "Взял твой сплит ({split}) — вот твоя программа на неделю, бро:",
    "en": "Got your split ({split}) — here's your program for the week, bro:",
    "fr": "J'ai pris ton split ({split}) — voici ton programme pour la semaine, champion :",
}
_WEEK_OUTRO = {
    "ru": "Погнали по дням! 💪",
    "en": "Let's get after it, day by day! 💪",
    "fr": "C'est parti, jour après jour ! 💪",
}


def _format_exercise_line(index: int, exercise: dict, language: str) -> str:
    """Та же грамматика, что и в fallback-текстах single-day программ (см. utils.pluralize_sets)."""
    lang = pick_language(language)
    is_numeric_reps = str(exercise["reps"]).strip().replace("-", "").isdigit()

    if lang == "ru":
        reps_part = f"{exercise['reps']} повторений" if is_numeric_reps else exercise["reps"]
        return f"{index + 1}. {exercise['name']} — {exercise['sets']} {pluralize_sets(exercise['sets'])} × {reps_part} — {exercise['why']}"
    if lang == "fr":
        reps_part = f"{exercise['reps']} répétitions" if is_numeric_reps else exercise["reps"]
        sets_word = "série" if exercise["sets"] == 1 else "séries"
        return f"{index + 1}. {exercise['name']} — {exercise['sets']} {sets_word} × {reps_part} — {exercise['why']}"

    reps_part = f"{exercise['reps']} reps" if is_numeric_reps else exercise["reps"]
    sets_word = "set" if exercise["sets"] == 1 else "sets"
    return f"{index + 1}. {exercise['name']} — {exercise['sets']} {sets_word} × {reps_part} — {exercise['why']}"


def _assemble_week_text(split_key: str, days: list, language: str) -> str:
    """Собирает единое сообщение для Telegram из всех дней сплита (см. generate_split_program)."""
    lang = pick_language(language)
    lines = [_WEEK_INTRO[lang].format(split=split_label(split_key, language)), ""]

    for day_index, day in enumerate(days):
        lines.append(_DAY_HEADER[lang].format(n=day_index + 1, title=day["day_title"]))
        for ex_index, exercise in enumerate(day["exercises"]):
            lines.append(_format_exercise_line(ex_index, exercise, language))
        lines.append("")

    lines.append(_WEEK_OUTRO[lang])
    return "\n".join(lines)


async def generate_split_program(user_id: int, chosen_split: str, goal: str, language: str) -> dict:
    """
    Генерирует полную недельную программу по выбранному сплиту: один вызов GPT на
    каждый день (см. _generate_split_day), для дней-вариаций передаёт упражнения
    соответствующего первого дня, чтобы GPT не повторялся.

    Возвращает {"text": str, "days": [{"day_title": str, "exercises": [...]}, ...]} —
    "text" уже включает заголовки по дням, "days" — для сохранения и Web App (см.
    database.save_user_program, api.py: GET /api/user/{user_id}/program/latest).
    """
    if chosen_split not in SPLIT_DAY_FOCUS:
        raise ValueError(f"Неизвестный тип сплита: {chosen_split!r}")
    if goal not in SPLIT_GOALS:
        raise ValueError(f"Неизвестная цель для сплита: {goal!r}")

    profile = await get_fitness_profile(user_id)
    profile_payload = _profile_payload(profile)

    day_focuses = SPLIT_DAY_FOCUS[chosen_split]
    days: list = []

    for muscle_focus in day_focuses:
        previous_day_exercises = None
        if "(variation)" in muscle_focus:
            base = _base_muscle_focus(muscle_focus)
            for prior_index, prior_focus in enumerate(day_focuses[: len(days)]):
                if _base_muscle_focus(prior_focus) == base:
                    previous_day_exercises = days[prior_index]["exercises"]
                    break

        day = await _generate_split_day(muscle_focus, goal, profile_payload, language, previous_day_exercises)
        days.append(day)

    text = _assemble_week_text(chosen_split, days, language)
    return {"text": text, "days": days}


def shorten_program_day(day: dict, target_exercise_count: int) -> dict:
    """
    Сокращает один день программы до target_exercise_count упражнений — чисто
    механическая операция (без GPT): упражнения уже отсортированы по приоритету при
    генерации (многосуставные -> изоляция), поэтому просто обрезаем с конца.
    Premium-функция (см. api.py: POST /api/user/{user_id}/program/shorten).
    """
    exercises = day["exercises"]
    if len(exercises) <= target_exercise_count:
        return day
    return {**day, "exercises": exercises[:target_exercise_count]}
