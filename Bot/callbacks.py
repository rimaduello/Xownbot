from telegram.ext import (
    CallbackContext,
)

from Core.logger import get_logger

logger = get_logger("BOT")


async def delete_download_request(context: CallbackContext):
    data = context.job.data
    dnldr = context.chat_data.pop(data["hash_str"], None)
    await data["msg"].delete()
    logger.info(f"cleaned download options {dnldr.url}")
