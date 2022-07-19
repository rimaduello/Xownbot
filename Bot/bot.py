import hashlib
import os.path
import tempfile

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MessageEntity,
    Message,
)
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CallbackContext,
    filters,
    CallbackQueryHandler,
)

import Bot.uploader as api_client
from Core.config import settings
from Core.logger import get_logger
from Download.downloader import get_downloader, DOWNLOADER_MAP, BaseDownloader

logger = get_logger("BOT")


def msg__options(downloader: BaseDownloader, hash_str: str):
    msg_ = f"<b>{downloader.name}</b>"
    for k_, v_ in downloader.meta.items():
        msg_ += f"\n•\t<i>{k_}: {v_}</i>"
    msg_ += "\n" * 2
    msg_ += "choose desired quality"
    kybrd_ = [
        [
            InlineKeyboardButton(
                f"{x['name']}: {round(x['size'] / (1024 ** 2), 2)} MB",
                callback_data=f"dl:video:{hash_str}:{x['name']}",
            )
        ]
        for x in sorted(downloader.qualities, key=lambda d_: d_["size"])
    ]
    if downloader.image_urls:
        kybrd_.append(
            [
                InlineKeyboardButton(
                    f"images ({len(downloader.image_urls)})",
                    callback_data=f"dl:image:{hash_str}",
                )
            ]
        )
    kybrd_ = InlineKeyboardMarkup(kybrd_)
    return msg_, kybrd_


async def cb__clean_request(context: CallbackContext):
    data = context.job.data
    dnldr = context.chat_data.pop(data["hash_str"], None)
    await data["msg"].delete()
    logger.info(f"cleaned download options {dnldr.url}")


async def handler__download_request(update: Update, context: CallbackContext):
    original_msg: Message = update.message
    url = original_msg.text
    logger.info(f"get download request for {url}")
    try:
        downloader = get_downloader(url)
    except KeyError:
        logger.warning(f"unsupported website: {url}")
        msg = f"this website is not supported. supported ones are {', '.join(DOWNLOADER_MAP.keys())}"
        await original_msg.reply_text(text=msg, quote=True)
        return

    wait_message = await original_msg.reply_text(
        text="please wait ...", quote=True
    )
    await downloader.prepare()
    await wait_message.delete()
    md_ = hashlib.md5(downloader.url.encode()).hexdigest()
    msg_, kybrd_ = msg__options(downloader, md_)
    options_msg = await original_msg.reply_html(
        text=msg_, quote=True, reply_markup=kybrd_
    )
    context.chat_data[md_] = downloader
    context.job_queue.run_once(
        cb__clean_request,
        settings.BOT_AUTO_DELETE,
        chat_id=update.effective_message.chat_id,
        data=dict(msg=options_msg, hash_str=md_),
    )


async def handler__download_image(update: Update, context: CallbackContext):
    query = update.callback_query
    logger.info(f"image download: {query.data}")
    hash_str = query.data.rsplit(":", 1)[-1]
    downloader: BaseDownloader = context.chat_data[hash_str]
    await query.answer()
    wait_message = await query.message.reply_text(
        text="please wait while fetching images ..."
    )
    for c_, src_ in enumerate(downloader.image_urls):
        with tempfile.TemporaryFile() as f_:
            await downloader.download_image(f_, c_)
            f_.seek(0)
            await query.message.reply_to_message.reply_document(
                f_, filename=src_.rsplit("/")[-1], quote=True
            )
    await wait_message.delete()


async def handler__download_video(update: Update, context: CallbackContext):
    query = update.callback_query
    logger.info(f"video download: {query.data}")
    hash_str, quality = query.data.rsplit(":", 2)[-2:]
    downloader: BaseDownloader = context.chat_data[hash_str]
    await query.answer()
    wait_message = await query.message.reply_text(
        text=f"please wait while fetching {quality} video ..."
    )
    downloader.set_quality(quality)
    with tempfile.TemporaryDirectory() as dir_:
        file_path = os.path.join(dir_, downloader.file_name)
        with open(file_path, "wb") as f_:
            await downloader.download_video(f_)
        file_uploaded = await api_client.upload(file_path, force_document=True)
    chat = update.effective_chat
    await chat.forward_from(settings.CLIENT_STORAGE, file_uploaded.id)
    await api_client.delete(file_uploaded.id)
    await wait_message.delete()


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
            handler__download_request,
        )
    )
    app.add_handler(
        CallbackQueryHandler(handler__download_image, pattern="^dl:image.+$")
    )
    app.add_handler(
        CallbackQueryHandler(handler__download_video, pattern="^dl:video.+$")
    )
    app.run_polling()
