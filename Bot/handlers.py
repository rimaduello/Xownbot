import hashlib
import os.path
import tempfile
from abc import abstractmethod

from telegram import (
    Update,
    Message,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    CallbackContext,
)

from Bot.tg_client import TgClient
from Bot.callbacks import delete_download_request
from Core.config import settings
from Core.logger import get_logger
from Download.downloader import get_downloader, DOWNLOADER_MAP, BaseDownloader

logger = get_logger("BOT")


class BaseDownloadHandle:
    downloader: BaseDownloader = None

    def __init__(self, update: Update, context: CallbackContext):
        self.update = update
        self.context = context
        self.query = update.callback_query

    async def exec(self):
        query = self.query
        logger.info(f"download request: {query.data}")
        hash_str = query.data.split(":", 3)[2]
        self.downloader = self.context.chat_data[hash_str]
        await query.answer()
        async with LoadingMessage(
            self.query.message,
            "please wait while fetching requested media ...",
        ):
            await self.handle()

    @classmethod
    async def run(cls, update: Update, context: CallbackContext):
        cls_ = cls(update=update, context=context)
        await cls_.exec()

    @abstractmethod
    async def handle(self):
        pass


class ImageDownloadHandle(BaseDownloadHandle):
    async def handle(self):
        for c_, src_ in enumerate(self.downloader.image_urls):
            with tempfile.TemporaryFile() as f_:
                await self.downloader.download_image(f_, c_)
                f_.seek(0)
                filename = src_.rsplit("/")[-1]
                await self.query.message.reply_to_message.reply_document(
                    f_, filename=filename, quote=True
                )


class VideoDownloadHandle(BaseDownloadHandle):
    async def handle(self):
        quality = self.query.data.rsplit(":", 1)[-1]
        self.downloader.set_quality(quality)
        tg_cl_ = TgClient()
        with tempfile.TemporaryDirectory() as dir_:
            file_path = os.path.join(dir_, self.downloader.file_name)
            with open(file_path, "wb") as f_:
                await self.downloader.download_video(f_)
            file_uploaded = await tg_cl_.upload(file_path, force_document=True)
        chat = self.update.effective_chat
        await chat.forward_from(settings.CLIENT_STORAGE, file_uploaded.id)
        await tg_cl_.delete(file_uploaded.id)


async def download_request(update: Update, context: CallbackContext):
    def download_options(downloader_: BaseDownloader, hash_str: str):
        msg__ = f"<b>{downloader_.name}</b>"
        for k_, v_ in downloader_.meta.items():
            msg__ += f"\n•\t<i>{k_}: {v_}</i>"
        msg__ += "\n" * 2
        msg__ += "choose desired quality"
        kybrd__ = [
            [
                InlineKeyboardButton(
                    f"{x['name']}: {round(x['size'] / (1024 ** 2), 2)} MB",
                    callback_data=f"dl:video:{hash_str}:{x['name']}",
                )
            ]
            for x in sorted(downloader_.qualities, key=lambda d_: d_["size"])
        ]
        if downloader_.image_urls:
            kybrd__.append(
                [
                    InlineKeyboardButton(
                        f"images ({len(downloader_.image_urls)})",
                        callback_data=f"dl:image:{hash_str}",
                    )
                ]
            )
        kybrd__ = InlineKeyboardMarkup(kybrd__)
        return msg__, kybrd__

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

    async with LoadingMessage(original_msg, "please wait ..."):
        await downloader.prepare()
    md_ = hashlib.md5(downloader.url.encode()).hexdigest()
    msg_, kybrd_ = download_options(downloader, md_)
    options_msg = await original_msg.reply_html(
        text=msg_, quote=True, reply_markup=kybrd_
    )
    context.chat_data[md_] = downloader
    context.job_queue.run_once(
        delete_download_request,
        settings.BOT_AUTO_DELETE,
        chat_id=update.effective_message.chat_id,
        data=dict(msg=options_msg, hash_str=md_),
    )


class LoadingMessage:
    message_obj = None

    def __init__(self, original_msg, text: str):
        self.original_obj = original_msg
        self.text = text

    async def __aenter__(self):
        self.message_obj = await self.original_obj.reply_text(text=self.text)

    async def __aexit__(self, exc_type, exc_value, exc_traceback):
        await self.message_obj.delete()
