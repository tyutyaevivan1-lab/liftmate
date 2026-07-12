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

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден. Проверь файл .env (см. .env.example)")

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY не найден. Проверь файл .env (см. .env.example)")
