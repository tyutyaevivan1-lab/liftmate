"""Точка входа: запуск Telegram-бота LiftMate."""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import MenuButtonWebApp, WebAppInfo

import keyboards
from config import BOT_TOKEN, WEBAPP_URL
from database import close_pool, init_db
from handlers import router


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    # Готовим базу данных (создаём таблицы, если их ещё нет; заодно создаёт пул
    # подключений к PostgreSQL — см. database.get_pool)
    await init_db()

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    # MemoryStorage хранит FSM-состояние (например, ожидание недостающих данных о подходе)
    # в оперативной памяти — при перезапуске бота оно сбрасывается
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    # Постоянная кнопка меню (синяя иконка слева от поля ввода) — открывает тот же
    # Web App, что и кнопка в /exercises. Устанавливается глобально для всех чатов.
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(text="Menu", web_app=WebAppInfo(url=WEBAPP_URL))
    )

    # Список команд для нативного меню Telegram (при вводе "/"). language_code привязывает
    # список к языку Telegram-клиента пользователя; без language_code — запасной вариант
    # (английский) для всех остальных языков клиента.
    for lang in ("ru", "en", "fr"):
        await bot.set_my_commands(commands=keyboards.get_commands(lang), language_code=lang)
    await bot.set_my_commands(commands=keyboards.get_commands("en"))

    try:
        # Сбрасываем возможный webhook и накопленные апдейты перед началом polling
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
