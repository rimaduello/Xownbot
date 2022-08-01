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
from Core.config import Settings
from Core.logger import get_logger

logger = get_logger("BOT")


class StorageChatFilter(filters.UpdateFilter):
    def filter(self, update):
        return update.effective_chat.id == Settings.BOT_STORAGE


storage_chat_filter = StorageChatFilter()


async def dummy(*_, **__):
    return


def run():
    app = ApplicationBuilder().token(Settings.BOT_KEY)
    prx_url = Settings.HTTP_PROXY
    if prx_url:
        logger.info(f"using proxy {prx_url}")
        app = app.proxy_url(prx_url).get_updates_proxy_url(prx_url)
    app = app.read_timeout(Settings.BOT_READ_TIMEOUT)
    app = app.write_timeout(Settings.BOT_WRITE_TIMEOUT)
    app = app.pool_timeout(Settings.BOT_POOL_TIMEOUT)
    app = app.build()
    app.add_handler(MessageHandler(storage_chat_filter, dummy))
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
        CallbackQueryHandler(handlers.image_download, pattern="^dl:image.+$")
    )
    app.add_handler(
        CallbackQueryHandler(handlers.video_download, pattern="^dl:video.+$")
    )
    app.add_handler(
        CallbackQueryHandler(handlers.ssb_video_download, pattern="^dl:ssb.+$")
    )
    app.add_handler(MessageHandler(filters.VIDEO, handlers.video_upload))
    app.run_polling()
