"""
Генерация простой программы тренировки на один день через GPT-4o-mini:
1) "по цели" (набрать массу / похудеть / выносливость);
2) "на основе истории тренировок" пользователя (см. database.get_recent_distinct_exercises).

Учитывает профиль пользователя (см. database.get_fitness_profile: опыт, оборудование,
ограничения) — заполняется один раз через мини-опрос (см. handlers.py, states.ProfileStates)
перед первой генерацией.

Программа определяет только УПРАЖНЕНИЯ, КОЛИЧЕСТВО ПОДХОДОВ/ПОВТОРЕНИЙ и краткое "почему"
для каждого упражнения — конкретный вес пользователь вводит сам при выполнении.

GPT возвращает структурированный JSON (текст для Telegram + список упражнений отдельно),
чтобы одна и та же программа могла быть показана и в чате, и в виде карточек в Web App
(см. api.py: GET /api/user/{user_id}/program/latest, webapp/app.js).

Структура уже готова к будущему расширению на многодневную (например, недельную)
premium-программу — см. параметр num_days в generate_workout_program и
_ensure_premium_if_needed.
"""

import json
import logging
from typing import Optional

from openai import AsyncOpenAI

from config import OPENAI_API_KEY
from database import get_fitness_profile, get_recent_distinct_exercises
from exercises_data import pick_language

logger = logging.getLogger(__name__)

client = AsyncOpenAI(api_key=OPENAI_API_KEY)

GOALS = ("bulk", "cut", "endurance")

# Общая часть промпта (для обоих режимов): как учитывать профиль и в каком JSON-формате отвечать
_PROFILE_AND_OUTPUT_INSTRUCTIONS = """
Также учти профиль пользователя (поле "profile" во входном JSON):
- experience_months — стаж тренировок в месяцах (null, если неизвестен — тогда считай пользователя тренирующимся среднего уровня). Меньше 3 месяцев — упрощай технику, избегай сложных многосуставных/травмоопасных упражнений без уверенной техники, меньше объём. 3-12 месяцев — средний уровень. Больше 12 месяцев — можно больше объёма и сложности.
- equipment_type — что доступно: "free_weights" (только гантели/штанга), "machines" (только тренажёры), "full_gym" (полный зал, доступно всё), "home" (дом/минимум инвентаря — используй упражнения с собственным весом, эспандеры, максимум пару лёгких предметов). Подбирай упражнения СТРОГО из того, что реально доступно с этим оборудованием.
- equipment_details — уточнение пользователя своими словами о конкретном инвентаре (может быть null) — учти, если релевантно.
- limitations — травмы/ограничения (может быть null, если их нет) — избегай упражнений, небезопасных при этом ограничении, и при необходимости выбирай более щадящую альтернативу.

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
    Заглушка на будущее: сейчас программа всегда на 1 день, поэтому premium не требуется,
    и проверка всегда проходит без ограничений. Когда появится многодневная (например,
    недельная) программа — здесь нужно будет проверить database.get_user_stats(user_id)
    ["is_premium"] (колонка уже существует в user_stats) и отказывать не-premium
    пользователям при num_days > 1.
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

    num_days зарезервирован под будущую многодневную premium-программу — сейчас
    поддерживается только num_days=1.
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
