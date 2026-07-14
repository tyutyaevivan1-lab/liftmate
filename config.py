"""Загрузка конфигурации проекта (токены и ключи) из .env файла."""

import os

from dotenv import load_dotenv

# Подгружаем переменные окружения из файла .env
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
# Адрес задеплоенного Telegram Web App (меню упражнений). Можно переопределить в .env,
# по умолчанию используется уже задеплоенный адрес.
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://liftmate-webapp.vercel.app")
# Строка подключения к PostgreSQL. На Railway создаётся автоматически при подключении
# плагина PostgreSQL к проекту — ничего указывать руками не нужно. Для локальной
# разработки нужно завести .env самому (см. подсказку в ValueError ниже и README.md).
DATABASE_URL = os.getenv("DATABASE_URL")
# Токен ОДНОГО Telegraph-аккаунта бота (см. program.py: _get_telegraph_client) — создаётся
# один раз через create_account() и переиспользуется для всех страниц с программами
# тренировок. Необязателен: если не задан (или Telegraph недоступен), программа на
# несколько дней отправляется текстом отдельными сообщениями по дням (см. program.publish_program).
TELEGRAPH_ACCESS_TOKEN = os.getenv("TELEGRAPH_ACCESS_TOKEN")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден. Проверь файл .env (см. .env.example)")

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY не найден. Проверь файл .env (см. .env.example)")

if not DATABASE_URL:
    raise ValueError(
        "DATABASE_URL не найден.\n\n"
        "На Railway эта переменная появляется автоматически, как только к проекту "
        "подключён плагин PostgreSQL — ничего настраивать вручную не нужно.\n\n"
        "Для локальной разработки нужна своя PostgreSQL и строка подключения в .env, например:\n"
        "  DATABASE_URL=postgresql://postgres:password@localhost:5432/liftmate\n\n"
        "Поднять локальную PostgreSQL проще всего через Docker:\n"
        "  docker run --name liftmate-postgres -e POSTGRES_PASSWORD=password "
        "-e POSTGRES_DB=liftmate -p 5432:5432 -d postgres\n\n"
        "Либо возьми готовую строку подключения из самого Railway-проекта "
        "(Postgres-плагин → вкладка Variables → DATABASE_URL) и вставь её в .env.\n"
        "См. также README.md."
    )
