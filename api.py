"""
API-сервер LiftMate для Web App (FastAPI).

Отдаёт Web App'у (https://liftmate-webapp.vercel.app) реальные данные тренировок из
той же PostgreSQL базы (см. database.py, DATABASE_URL), которую использует Telegram-бот
(main.py). Запускается ОТДЕЛЬНЫМ процессом от бота, в т.ч. на отдельном Railway-сервере —
общая база данных это и обеспечивает. Пояснение к запуску — в самом низу файла и в README.md.

--------------------------------------------------------------------------------
Про защиту через Telegram initData (почему это нужно и как это работает)
--------------------------------------------------------------------------------
Любой человек может открыть эти эндпоинты напрямую (curl, браузер) и попытаться
запросить данные ЛЮБОГО user_id — просто подставив число в URL. Без проверки это
означало бы, что кто угодно может прочитать чужие тренировки.

Telegram решает эту проблему так: когда бот открывает Web App внутри Telegram,
клиент Telegram сам добавляет в `window.Telegram.WebApp.initData` строку с данными
о текущем пользователе (id, имя и т.д.) и полем "hash" — подписью этих данных,
посчитанной СЕРВЕРАМИ ТЕЛЕГРАМА с использованием секрета, известного только
Telegram и владельцу бота (bot token). Подделать эту подпись, не зная bot token,
невозможно.

Проверка на нашей стороне (см. `_validate_init_data` ниже) повторяет тот же
алгоритм с тем же bot token:
1. Разбираем initData на пары key=value, убираем поле "hash".
2. Сортируем оставшиеся пары по ключу и склеиваем в "data_check_string".
3. Считаем secret_key = HMAC-SHA256("WebAppData", bot_token).
4. Считаем HMAC-SHA256(secret_key, data_check_string) — если результат совпал
   с полученным "hash", значит данные действительно от Telegram и не подделаны.
5. Дополнительно проверяем, что initData не протухла (auth_date не старше суток) —
   иначе можно было бы годами переиспользовать однажды подсмотренную initData.

Если подпись верна, мы достаём user.id из ПРОВЕРЕННЫХ данных и сверяем его с
user_id из URL: пользователь может смотреть только СВОИ тренировки, даже если
он руками поменяет число в адресной строке Web App.

Фронтенд должен присылать initData в заголовке `Authorization: Bearer <initData>`
при каждом запросе (Telegram.WebApp.initData — уже готовая строка, ничего парсить
самим не нужно на стороне клиента, см. webapp/app.js).
"""

import hashlib
import hmac
import json
import logging
import time
from typing import Optional
from urllib.parse import parse_qsl

from fastapi import Depends, FastAPI, Header, HTTPException, Path, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config import BOT_TOKEN, WEBAPP_URL
from database import close_pool, get_last_workout, get_user_language, get_workout_history, init_db

# initData считается действительной не дольше суток — после этого Web App должен
# быть переоткрыт заново (Telegram сам обновляет initData при каждом открытии)
INIT_DATA_MAX_AGE_SECONDS = 24 * 60 * 60

# Логи идут в stdout — именно их показывает `railway logs` (или любой другой хостинг).
# Без явной настройки uvicorn показывает только access-log ("GET ... 422"), а причину
# ошибки не видно вообще — это и мешало диагностировать проблему из отчёта пользователя.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("liftmate.api")

ALLOWED_ORIGINS = [WEBAPP_URL, "http://localhost:8765", "http://127.0.0.1:8765"]

app = FastAPI(
    title="LiftMate API",
    description="Данные тренировок для LiftMate Web App",
    version="1.0.0",
)

# Разрешаем запросы только с задеплоенного Web App — см. requirements.txt/README
# для локального запуска (localhost там тоже добавлен, чтобы можно было тестировать
# сам webapp/ с file:// или локального dev-сервера без пересборки CORS на лету)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """
    Логирует ПОЛНУЮ причину любого 422 (какое именно поле не прошло валидацию и почему).
    Без этого обработчика FastAPI сам вернёт корректный 422 с деталями в теле ответа, но
    в логах хостинга (например, Railway) видна только access-log строка вида
    "GET /api/... 422" — самой причины там нет, и диагностировать проблему вслепую,
    как в этом случае, невозможно.
    """
    header_names = list(request.headers.keys())
    logger.warning(
        "422 Unprocessable Content на %s %s | ошибки валидации: %s | заголовки запроса: %s",
        request.method,
        request.url.path,
        exc.errors(),
        header_names,
    )

    # Самый вероятный практический случай: задеплоенный webapp/app.js устарел и всё ещё
    # шлёт старый заголовок X-Telegram-Init-Data вместо Authorization: Bearer <initData>
    # (или наоборот, если старый api.py откатили). Это сразу видно в логах, а не только
    # в теле ответа, которое никто не смотрит на проде.
    # ВАЖНО: error["loc"] — это tuple, а не list, и хранит имя заголовка ТАК, КАК ОНО
    # ЗАДАНО В alias (здесь — "Authorization" с большой буквы) — сравнивать нужно
    # регистронезависимо и приводя к одному типу, иначе проверка никогда не сработает.
    missing_authorization = any(
        tuple(str(part).lower() for part in error.get("loc", ())) == ("header", "authorization")
        for error in exc.errors()
    )
    if missing_authorization:
        if "x-telegram-init-data" in header_names:
            logger.warning(
                "ПОХОЖЕ НАЙДЕНА ПРИЧИНА: клиент прислал заголовок 'X-Telegram-Init-Data', "
                "а сервер ждёт 'Authorization: Bearer <initData>'. Скорее всего, задеплоенный "
                "webapp/app.js устарел (или наоборот — откатили api.py). Проверь, что обе "
                "стороны используют один и тот же формат заголовка (см. require_telegram_user)."
            )
        else:
            logger.warning(
                "Заголовок Authorization отсутствует в запросе вовсе (нет ни его, ни старого "
                "X-Telegram-Init-Data) — проверь, что фронтенд действительно отправляет "
                "заголовок Authorization при запросе к этому эндпоинту."
            )

    return JSONResponse(status_code=422, content={"detail": exc.errors()})


@app.on_event("startup")
async def on_startup() -> None:
    """Гарантируем, что таблицы существуют, даже если API запущен раньше бота (создаёт и пул подключений к PostgreSQL)."""
    await init_db()
    logger.info("LiftMate API запущен. Разрешённые CORS origins: %s", ALLOWED_ORIGINS)
    logger.info(
        "BOT_TOKEN настроен: %s",
        "да" if BOT_TOKEN else "НЕТ — initData никогда не пройдёт проверку! Проверь переменные окружения.",
    )


@app.on_event("shutdown")
async def on_shutdown() -> None:
    """Аккуратно закрываем пул подключений к PostgreSQL при остановке сервера."""
    await close_pool()


# ---------------------------------------------------------------------------
# Валидация Telegram initData (см. пояснение в начале файла)
# ---------------------------------------------------------------------------


def _validate_init_data(init_data: str, bot_token: str) -> dict:
    """
    Проверяет подпись initData и возвращает распарсенный словарь пользователя
    Telegram ({"id": ..., "first_name": ..., ...}). Бросает ValueError с описанием
    причины, если подпись неверна, данные протухли или структура некорректна.
    """
    pairs = dict(parse_qsl(init_data, strict_parsing=True))

    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise ValueError("в initData нет поля hash")

    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(pairs.items()))

    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        raise ValueError("подпись initData не совпадает — данные подделаны или bot token не тот")

    auth_date = int(pairs.get("auth_date", 0))
    if time.time() - auth_date > INIT_DATA_MAX_AGE_SECONDS:
        raise ValueError("initData устарела — открой Web App заново")

    user_raw = pairs.get("user")
    if not user_raw:
        raise ValueError("в initData нет данных о пользователе")

    return json.loads(user_raw)


async def require_telegram_user(
    request: Request,
    authorization: str = Header(..., alias="Authorization"),
) -> dict:
    """
    FastAPI-зависимость: ждёт заголовок "Authorization: Bearer <initData>", проверяет
    подпись и возвращает провалидированного пользователя Telegram.

    Эта функция запускается, ТОЛЬКО если сам заголовок Authorization присутствует —
    если он отсутствует вовсе, FastAPI вернёт 422 ещё до вызова этой функции (см.
    handle_validation_error выше, где это отдельно логируется).
    """
    if not authorization.startswith("Bearer "):
        logger.warning(
            "Authorization header в неверном формате на %s %s (не начинается с 'Bearer '): %r",
            request.method,
            request.url.path,
            authorization[:20] + "…" if len(authorization) > 20 else authorization,
        )
        raise HTTPException(
            status_code=401,
            detail="Authorization header должен быть в формате 'Bearer <initData>'",
        )

    init_data = authorization[len("Bearer "):]

    try:
        user = _validate_init_data(init_data, BOT_TOKEN)
    except ValueError as exc:
        logger.warning(
            "Не прошла проверка initData на %s %s: %s | initData (первые 80 символов): %r",
            request.method,
            request.url.path,
            exc,
            init_data[:80],
        )
        raise HTTPException(status_code=401, detail=f"Invalid Telegram initData: {exc}") from exc

    logger.info("Успешная аутентификация user_id=%s на %s %s", user.get("id"), request.method, request.url.path)
    return user


def _ensure_matches_authenticated_user(user_id: int, telegram_user: dict) -> None:
    """Пользователь может запрашивать только свои собственные данные."""
    if telegram_user.get("id") != user_id:
        logger.warning(
            "user_id из URL (%s) не совпадает с аутентифицированным пользователем (%s)",
            user_id,
            telegram_user.get("id"),
        )
        raise HTTPException(
            status_code=403,
            detail="user_id не совпадает с пользователем из initData",
        )


# ---------------------------------------------------------------------------
# Модели ответа
# ---------------------------------------------------------------------------


class WorkoutEntry(BaseModel):
    date: str
    weight: float
    reps: int
    sets: int


class UserSettings(BaseModel):
    # None, если пользователь ещё ни разу не вызывал /language в боте — Web App
    # в этом случае сам решает, какой язык показать по умолчанию (см. webapp/app.js)
    language: Optional[str]


def _to_entry(row: dict) -> WorkoutEntry:
    # created_at хранится как полный ISO-datetime ("2026-07-01T18:32:00.123456"),
    # а Web App'у нужна только дата — берём часть до "T"
    return WorkoutEntry(
        date=row["created_at"].split("T")[0],
        weight=row["weight"],
        reps=row["reps"],
        sets=row["sets"],
    )


# ---------------------------------------------------------------------------
# Эндпоинты
# ---------------------------------------------------------------------------


@app.get("/api/user/{user_id}/exercises/{exercise_name}/history", response_model=list[WorkoutEntry])
async def get_exercise_history(
    user_id: int = Path(..., description="Telegram user ID"),
    exercise_name: str = Path(..., description="Название упражнения (en, как хранится в БД)"),
    telegram_user: dict = Depends(require_telegram_user),
) -> list[WorkoutEntry]:
    """
    История тренировок пользователя по упражнению, от старой записи к новой.
    Если записей нет — просто пустой список, это не ошибка (новое упражнение,
    опечатка в названии и т.п. — фронтенду достаточно увидеть "[]").
    """
    _ensure_matches_authenticated_user(user_id, telegram_user)

    normalized_name = exercise_name.strip().lower()
    rows = await get_workout_history(user_id, normalized_name)
    logger.info(
        "history: user_id=%s exercise_name=%r (нормализовано: %r) -> %d записей",
        user_id, exercise_name, normalized_name, len(rows),
    )
    return [_to_entry(row) for row in rows]


@app.get("/api/user/{user_id}/exercises/{exercise_name}/last", response_model=Optional[WorkoutEntry])
async def get_exercise_last(
    user_id: int = Path(..., description="Telegram user ID"),
    exercise_name: str = Path(..., description="Название упражнения (en, как хранится в БД)"),
    telegram_user: dict = Depends(require_telegram_user),
) -> Optional[WorkoutEntry]:
    """
    Последняя запись по упражнению (переиспользует database.get_last_workout —
    ту же функцию, что использует бот для сравнения прогресса). null, если
    записей ещё не было — тоже не ошибка.
    """
    _ensure_matches_authenticated_user(user_id, telegram_user)

    normalized_name = exercise_name.strip().lower()
    row = await get_last_workout(user_id, normalized_name)
    logger.info(
        "last: user_id=%s exercise_name=%r (нормализовано: %r) -> %s",
        user_id, exercise_name, normalized_name, "найдена" if row else "нет записей",
    )
    return _to_entry(row) if row else None


@app.get("/api/user/{user_id}/settings", response_model=UserSettings)
async def get_user_settings(
    user_id: int = Path(..., description="Telegram user ID"),
    telegram_user: dict = Depends(require_telegram_user),
) -> UserSettings:
    """
    Язык интерфейса, который пользователь уже выбрал в боте через /language —
    Web App использует его же, без отдельного выбора языка внутри самого приложения.
    """
    _ensure_matches_authenticated_user(user_id, telegram_user)

    language = await get_user_language(user_id)
    logger.info("settings: user_id=%s -> language=%r", user_id, language)
    return UserSettings(language=language)


# ---------------------------------------------------------------------------
# Локальный запуск: `python api.py` (для uvicorn api:app --reload см. README.md)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
