"""
Работа с OpenAI (GPT-4o-mini):
1) разбор свободного текста о тренировке в структурированные данные;
2) разбор ответа пользователя на уточняющий вопрос о недостающих данных;
3) генерация дружеского ответа пользователю на его языке (в т.ч. уточняющих вопросов).
"""

import json
import logging
from typing import Optional

from openai import AsyncOpenAI

from config import OPENAI_API_KEY
from utils import pluralize_sets, suggest_next_weight

logger = logging.getLogger(__name__)

client = AsyncOpenAI(api_key=OPENAI_API_KEY)

REQUIRED_FIELDS = ("weight", "reps", "sets")


def _to_optional_number(value, cast):
    """Приводит значение к числу нужного типа, либо возвращает None, если данных нет."""
    return None if value is None else cast(value)


def get_missing_fields(data: dict) -> list:
    """Возвращает список отсутствующих обязательных полей записи о тренировке."""
    return [field for field in REQUIRED_FIELDS if data.get(field) is None]


def _is_russian(language: str) -> bool:
    """Проверяет, является ли определённый язык русским (по коду или названию)."""
    return (language or "").strip().lower().startswith("ru")


# ---------------------------------------------------------------------------
# 1. Промпт для разбора текста в структурированные данные (с учётом контекста диалога)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_PARSE = """Ты — помощник, который распознаёт сообщения о тренировках в зале и превращает их в структурированные данные.

Тебе на вход придёт JSON:
- text — новое сообщение пользователя
- history — последние несколько реплик переписки с этим пользователем (список объектов {"role": "user"|"bot", "text": "..."}) в хронологическом порядке; может быть пустым
- last_saved_workout — последняя запись о тренировке, уже сохранённая в базе для этого пользователя (exercise_name, weight, reps, sets), или null, если записей ещё не было

Пользователь пишет о тренировке в свободной форме НА ЛЮБОМ ЯЗЫКЕ, независимо от того, на каком языке ведётся остальной диалог. Иногда это полное описание нового подхода, например:
"жим лежа 80кг на 8 раз, 3 подхода"
"bench press 80kg for 8 reps, 3 sets"

А иногда — короткое ДОПОЛНЕНИЕ или ПОПРАВКА к последней обсуждённой тренировке (last_saved_workout), например:
"ещё один подход", "i made one set more", "add one more set", "сделал ещё раз побольше", "actually it was 90kg"
Используй history и last_saved_workout, чтобы понять такие сообщения: они относятся к упражнению из last_saved_workout, и нужно вычислить НОВОЕ АБСОЛЮТНОЕ значение изменившегося поля (например, если last_saved_workout.sets = 3, а сообщение "ещё один подход" — новое значение sets будет 4).

Определи, к какому из четырёх типов относится сообщение, и верни ТОЛЬКО валидный JSON без пояснений и markdown:

1. "new_entry" — сообщение описывает НОВЫЙ подход/упражнение (не продолжение last_saved_workout):
{"action": "new_entry", "exercise_name": "название упражнения в нижнем регистре, нормализованное", "weight": число_или_null, "reps": число_или_null, "sets": число_или_null}

2. "update_last" — сообщение это дополнение/поправка к last_saved_workout (например "ещё подход", "on rajoute une série", "actually it was 90kg"). ВАЖНО: такое действие возможно, ТОЛЬКО если last_saved_workout не null. Верни новое АБСОЛЮТНОЕ значение для изменившегося поля, а остальные (weight/reps/sets), если они не менялись, можешь оставить null — код сам подставит их из last_saved_workout:
{"action": "update_last", "weight": число_или_null, "reps": число_или_null, "sets": число_или_null}

3. "unclear" — сообщение похоже на дополнение к тренировке, но даже с учётом history/last_saved_workout непонятно, о чём именно идёт речь:
{"action": "unclear"}

4. "not_workout" — сообщение вообще не о тренировке (обычная болтовня, вопрос не по теме и т.д.):
{"action": "not_workout"}

ВАЖНО:
- weight, reps и sets нельзя додумывать: если значение не следует ни из текущего сообщения, ни из history/last_saved_workout — верни null.
- Не определяй и не возвращай язык сообщения — он не нужен, ответ пользователю всегда формируется на языке, который он явно выбрал в настройках (это делает другая часть системы).
- Поле weight ВСЕГДА представляет вес в КИЛОГРАММАХ. Если пользователь явно указал другую единицу измерения (lbs, pounds, фунты) — переведи значение в килограммы (1 lb ≈ 0.453592 kg) и верни результат уже в kg. Если единица измерения не указана вообще — считай, что число уже в килограммах, ничего не переводи.
"""


async def parse_workout_message(
    text: str,
    history: Optional[list] = None,
    last_saved: Optional[dict] = None,
) -> Optional[dict]:
    """
    Отправляет текст пользователя (вместе с недавней историей переписки и последней
    сохранённой записью) в GPT-4o-mini и получает структурированные данные о тренировке.
    Распознавание работает независимо от языка сообщения — язык ответа пользователю
    определяется отдельно, на основе явно выбранного им языка интерфейса (не отсюда).

    Возвращает словарь с ключом "action" ("new_entry"|"update_last"|"unclear"|"not_workout").
    Для "new_entry"/"update_last" также содержит weight/reps/sets (могут быть None, если не
    удалось определить — для "update_last" недостающие поля нужно дозаполнить значениями из
    last_saved_workout на стороне вызывающего кода). Для "new_entry" также содержит exercise_name.

    Возвращает None только в случае ошибки при обращении к OpenAI.
    """
    payload = {
        "text": text,
        "history": history or [],
        "last_saved_workout": (
            {
                "exercise_name": last_saved["exercise_name"],
                "weight": last_saved["weight"],
                "reps": last_saved["reps"],
                "sets": last_saved["sets"],
            }
            if last_saved
            else None
        ),
    }

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_PARSE},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content)
        action = data.get("action", "not_workout")

        if action not in ("new_entry", "update_last"):
            return {"action": action}

        result = {
            "action": action,
            "weight": _to_optional_number(data.get("weight"), float),
            "reps": _to_optional_number(data.get("reps"), int),
            "sets": _to_optional_number(data.get("sets"), int),
        }
        if action == "new_entry":
            result["exercise_name"] = str(data["exercise_name"]).strip().lower()

        return result
    except Exception:
        logger.exception("Не удалось разобрать сообщение через OpenAI")
        return None


def not_understood_message(language: str) -> str:
    """Мягкое, дружеское сообщение на случай, если текст вообще не похож на описание тренировки."""
    lang = (language or "en").strip().lower()

    if lang.startswith("ru"):
        return "Хм, не совсем понял 🙂 Расскажи как для своего — какое упражнение, с каким весом и сколько раз?"
    if lang.startswith("fr"):
        return "Hmm, je n'ai pas trop saisi 🙂 Dis-moi ça comme à un pote — quel exercice, quel poids, combien de répétitions ?"
    return "Hmm, didn't quite catch that 🙂 Just tell me like you'd tell a friend — what exercise, what weight, how many reps?"


UNCLEAR_SYSTEM_PROMPT = """Ты — LiftMate, бот-трекер тренировок, общаешься как близкий друг по залу: тепло, неформально, дружелюбно, без наигранности.

Пользователь написал что-то похожее на дополнение к тренировке (например "ещё подход", "добавил веса"), но даже с учётом истории переписки непонятно, к какому упражнению это относится или что именно изменилось.

На вход придёт JSON: {"language": "код языка", "text": "сообщение пользователя"}.

Сгенерируй ОДНО короткое дружеское сообщение НА ЯЗЫКЕ "language", которое мягко уточняет, к какому упражнению это относится и/или что именно изменилось. Без markdown и кавычек, 1-2 предложения.
"""


def _fallback_unclear_reply(language: str) -> str:
    """Запасной ответ на случай ошибки OpenAI при генерации уточнения для неоднозначного сообщения."""
    if _is_russian(language):
        return "Не понял, к какому упражнению это относится — уточнишь, бро?"
    if (language or "").strip().lower().startswith("fr"):
        return "Je ne suis pas sûr de quel exercice tu parles — tu peux préciser ?"
    return "Not sure which exercise you mean — mind clarifying, bro?"


async def generate_unclear_reply(*, language: str, text: str) -> str:
    """Генерирует дружеский уточняющий вопрос, когда сообщение неоднозначно даже с учётом контекста."""
    payload = {"language": language, "text": text}
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": UNCLEAR_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0.7,
        )
        reply = response.choices[0].message.content.strip()
        return reply if reply else _fallback_unclear_reply(language)
    except Exception:
        logger.exception("Не удалось сгенерировать уточнение для неоднозначного сообщения")
        return _fallback_unclear_reply(language)


# ---------------------------------------------------------------------------
# 2. Промпт для разбора ответа пользователя на уточняющий вопрос
# ---------------------------------------------------------------------------

CLARIFICATION_REPLY_PROMPT = """Ты помогаешь разобрать ответ пользователя на уточняющий вопрос о тренировке.

Контекст: бот уже сохранил незавершённые данные о подходе (pending) и спросил у пользователя недостающие поля (missing_fields). Тебе на вход придёт JSON:
- pending — уже известные данные (exercise_name, weight, reps, sets; null — если поле неизвестно)
- missing_fields — список полей, которые бот попросил уточнить ("weight", "reps" и/или "sets")
- language — язык диалога
- reply — новое сообщение пользователя

Определи, чем является reply, и верни ОДИН из трёх вариантов действия:

1. "fill" — пользователь отвечает на вопрос и указывает недостающие данные. Это может быть как голое число ("8"), так и фраза ("8 повторений", "16кг и 3 подхода", "on a fait 10 reps"). Извлеки числовые значения для полей из missing_fields (если заодно уточнил и другое поле — тоже верни).
2. "new_workout" — вместо ответа пользователь описывает СОВЕРШЕННО ДРУГОЕ упражнение или новый подход, никак не связанный с текущим missing_fields контекстом (упомянуто другое название упражнения).
3. "irrelevant" — сообщение не отвечает на вопрос и не похоже на новую тренировку (болтовня, вопрос не по теме и т.п.)

Верни ТОЛЬКО валидный JSON без пояснений и markdown:
{"action": "fill" | "new_workout" | "irrelevant", "weight": число_или_null, "reps": число_или_null, "sets": число_или_null}
"""


async def parse_clarification_reply(
    *,
    pending: dict,
    missing: list,
    language: str,
    text: str,
) -> dict:
    """
    Разбирает ответ пользователя на уточняющий вопрос о недостающих данных тренировки.

    Возвращает словарь {"action": "fill"|"new_workout"|"irrelevant", "weight":.., "reps":.., "sets":..}.
    При ошибке OpenAI считает ответ нерелевантным ("irrelevant"), чтобы не зависнуть в ожидании.
    """
    payload = {
        "pending": {
            "exercise_name": pending.get("exercise_name"),
            "weight": pending.get("weight"),
            "reps": pending.get("reps"),
            "sets": pending.get("sets"),
        },
        "missing_fields": missing,
        "language": language,
        "reply": text,
    }

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": CLARIFICATION_REPLY_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content)

        return {
            "action": data.get("action", "irrelevant"),
            "weight": _to_optional_number(data.get("weight"), float),
            "reps": _to_optional_number(data.get("reps"), int),
            "sets": _to_optional_number(data.get("sets"), int),
        }
    except Exception:
        logger.exception("Не удалось разобрать ответ на уточняющий вопрос через OpenAI")
        return {"action": "irrelevant", "weight": None, "reps": None, "sets": None}


# ---------------------------------------------------------------------------
# 3. Промпт для генерации дружеского ответа в стиле "бро по залу"
# ---------------------------------------------------------------------------

REPLY_SYSTEM_PROMPT = """Ты — LiftMate, бот-трекер тренировок, который общается с пользователем как близкий друг по спортзалу: неформально, тепло, с поддержкой, но без перебора со сленгом и без наигранности.

Тебе на вход придёт JSON с данными о только что сохранённом подходе и (опционально) данными о предыдущей попытке этого же упражнения. Твоя задача — сгенерировать ОДНО короткое сообщение пользователю.

Правила:
- Ответ должен быть НА ЯЗЫКЕ, указанном в поле "language" (пиши так, как написал бы носитель этого языка, не переводи дословно с русского).
- Тон — как у друга в зале, который искренне рад за тебя и подбадривает: разговорный, живой, но без наигранности и без спама сленгом. Примеры желаемого тона (не копируй дословно, адаптируй под цифры и язык):
  - "Красава, записал! Присед — 100кг × 5, 3 подхода. Юзаешь эту неделю на полную!"
  - "Огонь, сегодня жмёшь больше чем в прошлый раз! Так держать, бро"
  - "Записал! Сегодня чуть полегче чем в прошлый раз — окей, бывает, главное что был в зале"
  - На английском в том же духе: "Nice one, logged it!", "Solid work today, that's progress right there", "All good, we all have those days"
- Обязательно естественно упомяни в ответе: упражнение, вес, повторения И количество подходов. Если в JSON передано поле "sets_phrase" — используй его как готовую фразу для количества подходов ДОСЛОВНО, не изменяя окончание слова (это нужно для грамматически верного русского). Если "sets_phrase" отсутствует — сформулируй количество подходов сам, грамматически верно для языка ответа.
- Поле "situation" говорит, что именно сейчас происходит, и как реагировать:
  - "first" — это первая запись упражнения. Никаких сравнений и рекомендаций, просто тепло похвали, что записал.
  - "progress" — "weight" больше "previous_weight". Искренне порадуйся прогрессу, упомяни, что раньше было "previous_weight" кг. В ЭТОМ сообщении НЕ предлагай увеличить вес ещё больше — прогресс уже случился, дай его прожить, следующая рекомендация придёт в свой черёд.
  - "recommend" — вес не изменился, и пользователь сделал столько же или больше повторений, чем в прошлый раз (то есть текущий вес дался ему явно легко). Похвали как обычно, а затем ОРГАНИЧНО, своими словами предложи в следующий раз попробовать вес из поля "recommended_next_weight" (в кг) — как будто заметил, что человек явно готов к большему. Не используй каждый раз одну и ту же фразу-шаблон, формулируй по-разному в зависимости от контекста.
  - "repeat" — результат хуже, чем в прошлый раз (меньший вес, либо тот же вес но меньше повторений). Мягко подбодри без давления, упомяни, что раньше было "previous_weight" кг, и предложи в следующий раз просто повторить тот же вес "weight" ещё раз — без спешки наращивать дальше.
- ЕДИНИЦА ИЗМЕРЕНИЯ ВЕСА ВСЕГДА — КИЛОГРАММЫ. Значения "weight", "previous_weight" и "recommended_next_weight" уже даны в килограммах (это то, что реально хранится в базе данных). Используй «кг» при ответе на русском и «kg» на любом другом языке (в т.ч. английском). НИКОГДА не пиши lbs/pounds/фунты и не пересчитывай число — даже если для языка ответа привычнее фунты, единица должна остаться "kg"/"кг", чтобы совпадать с базой данных. Число "recommended_next_weight" уже правильно округлено — используй его как есть, не пересчитывай.
- Ответ — только сам текст сообщения, без кавычек, без markdown, 1-2 предложения.
"""


def _determine_situation(
    weight: float,
    reps: int,
    previous_weight: Optional[float],
    previous_reps: Optional[int],
) -> str:
    """
    Определяет, что сейчас происходит по сравнению с прошлой попыткой этого упражнения:
    "first" — первая запись; "progress" — вес вырос; "recommend" — вес тот же, но
    повторений столько же или больше (пора предложить прибавку); "repeat" — результат
    хуже (меньший вес, либо тот же вес с меньшим числом повторений).
    """
    if previous_weight is None:
        return "first"
    if weight > previous_weight:
        return "progress"
    if weight == previous_weight and previous_reps is not None and reps >= previous_reps:
        return "recommend"
    return "repeat"


def _fallback_reply(
    exercise_name: str,
    weight: float,
    reps: int,
    sets: int,
    previous_weight: Optional[float],
    previous_reps: Optional[int],
    language: str,
) -> str:
    """Запасной шаблонный ответ на случай ошибки OpenAI при генерации текста."""
    exercise_title = exercise_name.capitalize()
    situation = _determine_situation(weight, reps, previous_weight, previous_reps)
    recommended_weight = suggest_next_weight(weight) if situation == "recommend" else None

    if _is_russian(language):
        sets_phrase = f"{sets} {pluralize_sets(sets)}"
        if situation == "first":
            return f"Записал! {exercise_title} — {weight:g}кг × {reps}, {sets_phrase}."
        if situation == "progress":
            return (
                f"Красава, записал! {exercise_title} — {weight:g}кг × {reps}, {sets_phrase}. "
                f"Прогресс! Раньше было {previous_weight:g}кг — так держать!"
            )
        if situation == "recommend":
            return (
                f"Отлично, записал! {exercise_title} — {weight:g}кг × {reps}, {sets_phrase}. "
                f"В следующий раз попробуй {recommended_weight:g}кг — ты явно готов к большему!"
            )
        return (
            f"Записал! {exercise_title} — {weight:g}кг × {reps}, {sets_phrase}. "
            f"Раньше было {previous_weight:g}кг — в следующий раз попробуй повторить {weight:g}кг, всё нормально."
        )

    # Запасной вариант на английском для остальных языков
    sets_word = "set" if sets == 1 else "sets"
    if situation == "first":
        return f"Nice, logged it! {exercise_title} — {weight:g}kg × {reps}, {sets} {sets_word}."
    if situation == "progress":
        return (
            f"Nice one, logged it! {exercise_title} — {weight:g}kg × {reps}, {sets} {sets_word}. "
            f"Solid progress — last time it was {previous_weight:g}kg!"
        )
    if situation == "recommend":
        return (
            f"Nice, logged it! {exercise_title} — {weight:g}kg × {reps}, {sets} {sets_word}. "
            f"Try {recommended_weight:g}kg next time — you've clearly got more in the tank!"
        )
    return (
        f"Logged it! {exercise_title} — {weight:g}kg × {reps}, {sets} {sets_word}. "
        f"Last time was {previous_weight:g}kg — try repeating {weight:g}kg next time, all good."
    )


async def generate_friendly_reply(
    *,
    exercise_name: str,
    weight: float,
    reps: int,
    sets: int,
    language: str,
    previous_weight: Optional[float],
    previous_reps: Optional[int] = None,
) -> str:
    """
    Генерирует тёплый, дружеский ответ пользователю на его языке через GPT-4o-mini,
    учитывая прогресс по сравнению с предыдущей записью, и (если пользователь явно
    справился с текущим весом без проблем) органично предлагает следующий вес для прогрессии.
    """
    # Для русского языка заранее считаем грамматически верную фразу и передаём её как есть,
    # чтобы модель не ошиблась со склонением
    sets_phrase = f"{sets} {pluralize_sets(sets)}" if _is_russian(language) else None

    situation = _determine_situation(weight, reps, previous_weight, previous_reps)
    # Конкретное число для рекомендации считаем в Python (округление до шага в 1.25/2.5кг) —
    # это точная арифметика, которую не стоит доверять GPT, только формулировку вокруг неё
    recommended_next_weight = suggest_next_weight(weight) if situation == "recommend" else None

    payload = {
        "exercise_name": exercise_name,
        "weight": weight,
        "reps": reps,
        "sets": sets,
        "sets_phrase": sets_phrase,
        "language": language,
        "previous_weight": previous_weight,
        "situation": situation,
        "recommended_next_weight": recommended_next_weight,
    }

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": REPLY_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0.7,
        )
        reply = response.choices[0].message.content.strip()
        return reply if reply else _fallback_reply(
            exercise_name, weight, reps, sets, previous_weight, previous_reps, language
        )
    except Exception:
        logger.exception("Не удалось сгенерировать ответ через OpenAI, используем запасной вариант")
        return _fallback_reply(exercise_name, weight, reps, sets, previous_weight, previous_reps, language)


# ---------------------------------------------------------------------------
# 3.1 Промпт для подтверждения ОБНОВЛЕНИЯ уже существующей записи
#     (например, когда пользователь дополнил "ещё один подход")
# ---------------------------------------------------------------------------

UPDATE_REPLY_SYSTEM_PROMPT = """Ты — LiftMate, бот-трекер тренировок, общаешься как близкий друг по залу: тепло, неформально, дружелюбно, без наигранности.

Пользователь только что дополнил или поправил уже обсуждённую запись о подходе (например, добавил ещё один подход или уточнил вес). Тебе на вход придёт JSON с итоговыми, уже обновлёнными данными: exercise_name, weight, reps, sets, sets_phrase (готовая фраза для русского языка, если применимо), language.

Сгенерируй ОДНО короткое дружеское сообщение, которое подтверждает именно ОБНОВЛЕНИЕ существующей записи (а не первую запись с нуля) — например в духе "Красава, обновил! Теперь 4 подхода" или "Nice, updated — that's 4 sets now!". Обязательно упомяни итоговые: упражнение, вес, повторения и количество подходов (используй sets_phrase дословно для русского, если оно передано). ЕДИНИЦА ИЗМЕРЕНИЯ ВЕСА ВСЕГДА — КИЛОГРАММЫ (это то, что реально хранится в базе данных): используй «кг» на русском и «kg» на любом другом языке, НИКОГДА не пиши lbs/pounds/фунты и не пересчитывай число. Ответ НА ЯЗЫКЕ "language", без markdown и кавычек, 1-2 предложения.
"""


def _fallback_update_reply(exercise_name: str, weight: float, reps: int, sets: int, language: str) -> str:
    """Запасной шаблонный ответ-подтверждение обновления на случай ошибки OpenAI."""
    exercise_title = exercise_name.capitalize()

    if _is_russian(language):
        sets_phrase = f"{sets} {pluralize_sets(sets)}"
        return f"Обновил! {exercise_title} — {weight:g}кг × {reps}, теперь {sets_phrase}."

    sets_word = "set" if sets == 1 else "sets"
    return f"Updated! {exercise_title} — {weight:g}kg × {reps}, now {sets} {sets_word}."


async def generate_update_confirmation_reply(
    *,
    exercise_name: str,
    weight: float,
    reps: int,
    sets: int,
    language: str,
) -> str:
    """Генерирует дружеское подтверждение того, что уже существующая запись была обновлена."""
    sets_phrase = f"{sets} {pluralize_sets(sets)}" if _is_russian(language) else None

    payload = {
        "exercise_name": exercise_name,
        "weight": weight,
        "reps": reps,
        "sets": sets,
        "sets_phrase": sets_phrase,
        "language": language,
    }

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": UPDATE_REPLY_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0.7,
        )
        reply = response.choices[0].message.content.strip()
        return reply if reply else _fallback_update_reply(exercise_name, weight, reps, sets, language)
    except Exception:
        logger.exception("Не удалось сгенерировать подтверждение обновления через OpenAI, используем запасной вариант")
        return _fallback_update_reply(exercise_name, weight, reps, sets, language)


# ---------------------------------------------------------------------------
# 4. Промпт для генерации уточняющего вопроса о недостающих данных
# ---------------------------------------------------------------------------

CLARIFY_SYSTEM_PROMPT = """Ты — LiftMate, бот-трекер тренировок, общаешься как близкий друг по залу: тепло, неформально, дружелюбно, без наигранности (тот же тон, что и в остальных твоих ответах пользователю).

Пользователь описал подход, но указал не все данные. На вход придёт JSON:
- exercise_name — название упражнения
- known — то, что уже известно (weight, reps, sets; null, если поле неизвестно)
- missing_fields — список отсутствующих полей ("weight", "reps" и/или "sets")
- language — язык, на котором нужно ответить

Сгенерируй ОДНО короткое дружеское сообщение, которое:
- написано НА ЯЗЫКЕ "language" (так, как написал бы носитель этого языка, не переводи дословно)
- сначала тепло откликается на то, что уже известно (упражнение и уже известные цифры)
- затем вежливо просит уточнить именно недостающее: weight — с каким весом, reps — сколько повторений, sets — сколько подходов; если полей несколько — спроси про все компактно, одним сообщением
- ЕДИНИЦА ИЗМЕРЕНИЯ ВЕСА ВСЕГДА — КИЛОГРАММЫ (это то, что хранится в базе данных): если упоминаешь уже известный вес из "known", используй «кг» на русском и «kg» на любом другом языке. Если именно вес и спрашиваешь (weight есть в missing_fields) — либо не упоминай единицу вовсе, либо явно предполагай килограммы. НИКОГДА не пиши и не предлагай lbs/pounds/фунты.
- без markdown и кавычек, только сам текст сообщения, 1-2 предложения
"""

_FIELD_NAMES_RU = {"weight": "с каким весом", "reps": "сколько повторений", "sets": "сколько подходов"}
_FIELD_NAMES_EN = {"weight": "what weight", "reps": "how many reps", "sets": "how many sets"}


def _fallback_clarifying_question(exercise_name: str, missing: list, language: str) -> str:
    """Запасной шаблонный уточняющий вопрос на случай ошибки OpenAI."""
    exercise_title = exercise_name.capitalize()

    if _is_russian(language):
        question = " и ".join(_FIELD_NAMES_RU[field] for field in missing)
        return f"Записал {exercise_title}! Уточни, бро — {question}?"

    question = " and ".join(_FIELD_NAMES_EN[field] for field in missing)
    return f"Got it, {exercise_title}! Just need to know, bro — {question}?"


async def generate_clarifying_question(
    *,
    exercise_name: str,
    known: dict,
    missing: list,
    language: str,
) -> str:
    """
    Генерирует дружеский уточняющий вопрос о недостающих данных подхода
    (вес, повторения и/или подходы) на языке пользователя.
    """
    payload = {
        "exercise_name": exercise_name,
        "known": {field: known.get(field) for field in REQUIRED_FIELDS},
        "missing_fields": missing,
        "language": language,
    }

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": CLARIFY_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0.7,
        )
        text = response.choices[0].message.content.strip()
        return text if text else _fallback_clarifying_question(exercise_name, missing, language)
    except Exception:
        logger.exception("Не удалось сгенерировать уточняющий вопрос через OpenAI, используем запасной вариант")
        return _fallback_clarifying_question(exercise_name, missing, language)
