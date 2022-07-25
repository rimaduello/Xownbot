from telegram import (
    MessageEntity,
)
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    filters,
    CallbackQueryHandler,
)

from Bot import handlers
from Core.config import settings
from Core.logger import get_logger

logger = get_logger("BOT")


def run():
    app = ApplicationBuilder().token(settings.BOT_KEY)
    prx_url = settings.HTTP_PROXY
    if prx_url:
        logger.info(f"using proxy {prx_url}")
        app.proxy_url(prx_url).get_updates_proxy_url(prx_url)
    app.read_timeout(settings.BOT_READ_TIMEOUT)
    app.write_timeout(settings.BOT_WRITE_TIMEOUT)
    app = app.build()

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & (
                filters.Entity(MessageEntity.URL)
                | filters.Entity(MessageEntity.TEXT_LINK)
            ),
            handlers.download_request,
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            handlers.ImageDownloadHandle.run, pattern="^dl:image.+$"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            handlers.VideoDownloadHandle.run, pattern="^dl:video.+$"
        )
    )
    app.run_polling()
