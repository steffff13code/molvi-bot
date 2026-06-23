import asyncio

from aiogram import Bot, Dispatcher
from aiogram.types import MenuButtonWebApp, WebAppInfo
from loguru import logger

from bot.api import start_api
from bot.config import settings
from bot.db.database import init_db
from bot.handlers.help import router as help_router
from bot.handlers.start import router as start_router
from bot.handlers.voice import router as voice_router
from bot.logging import setup_logging
from bot.services.cleanup import start_cleanup_task


async def _setup_menu_button(bot: Bot) -> None:
    """Заменяет левую menu-кнопку (список команд) на кнопку «Сайт» (web_app)."""
    try:
        await bot.delete_my_commands()
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="Сайт",
                web_app=WebAppInfo(url=settings.landing_url),
            )
        )
        logger.info("Menu button set to web_app: {url}", url=settings.landing_url)
    except Exception as e:
        logger.warning("Failed to set web_app menu button ({e}); keeping default.", e=e)


async def main() -> None:
    setup_logging()
    logger.info("Starting Molvi bot (@molviai_bot)")

    await init_db()

    bot = Bot(token=settings.telegram_bot_token)
    dp = Dispatcher()

    dp.include_router(start_router)
    dp.include_router(voice_router)
    dp.include_router(help_router)

    await _setup_menu_button(bot)

    start_cleanup_task()

    # HTTP-API для админки (если задан порт/токен) — параллельно polling.
    if settings.api_port:
        await start_api(settings.api_port)
    else:
        logger.info("API not started (no PORT in env)")

    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Bot polling started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
