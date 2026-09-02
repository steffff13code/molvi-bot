import asyncio
import sys

from aiogram import Bot, Dispatcher
from aiogram.types import ErrorEvent, MenuButtonWebApp, WebAppInfo
from loguru import logger

from bot.api import start_api
from bot.config import settings
from bot.db.database import init_db
from bot.db.queries import log_event
from bot.handlers.help import router as help_router
from bot.handlers.records import router as records_router
from bot.handlers.start import router as start_router
from bot.handlers.voice import router as voice_router
from bot.logging import setup_logging
from bot.services import heartbeat
from bot.services.cleanup import start_cleanup_task
from bot.services.notify import notifier


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

    admin_chat_id = settings.admin_chat_id or settings.admin_id
    notifier.bind(bot, admin_chat_id)
    notifier.start()

    dp.include_router(start_router)
    dp.include_router(records_router)
    dp.include_router(voice_router)
    dp.include_router(help_router)

    @dp.errors()
    async def on_unhandled_error(event: ErrorEvent) -> bool:
        """Ловит любое исключение, не пойманное внутри хендлеров — раньше такое
        просто падало в лог, и владелец узнавал об аварии от пользователя."""
        update = event.update
        user = None
        if update.message and update.message.from_user:
            user = update.message.from_user
        elif update.callback_query and update.callback_query.from_user:
            user = update.callback_query.from_user
        user_id = user.id if user else None

        logger.opt(exception=event.exception).error(
            "Unhandled update exception (user_id={uid})", uid=user_id,
        )

        if user_id is not None:
            try:
                await log_event(user_id=user_id, type_="error", err_code="unhandled")
            except Exception:
                pass

        # ПДн: в группу — только user_id, без username/first_name.
        if notifier.is_group or user is None:
            who = f"user_id={user_id}" if user_id is not None else "неизвестный пользователь"
        else:
            uname = f" @{user.username}" if user.username else ""
            who = f"{user.first_name}{uname} (id={user_id})"

        notifier.notify(
            "error",
            f"🔥 Необработанная ошибка у {who}:\n{type(event.exception).__name__}: {event.exception}",
        )
        return True

    heartbeat.start(dp)

    await _setup_menu_button(bot)

    start_cleanup_task()

    # HTTP-API для админки (если задан порт/токен) — параллельно polling.
    if settings.api_port:
        await start_api(settings.api_port)
    else:
        logger.info("API not started (no PORT in env)")

    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Bot polling started")
    notifier.notify("boot", "✅ МОЛВИ запущен и начал polling.")
    await dp.start_polling(bot)


def _handle_exception(loop, context: dict) -> None:  # type: ignore[type-arg]
    exc = context.get("exception")
    msg = context.get("message", "Unknown asyncio error")
    if exc:
        logger.opt(exception=exc).error("Unhandled asyncio exception: {msg}", msg=msg)
        notifier.notify("error", f"🔥 Необработанное исключение asyncio: {type(exc).__name__}: {exc}")
    else:
        logger.error("Asyncio error: {msg}", msg=msg)
        notifier.notify("error", f"🔥 Ошибка asyncio-цикла: {msg}")


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    loop.set_exception_handler(_handle_exception)
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by KeyboardInterrupt")
    finally:
        loop.close()
        sys.exit(0)
