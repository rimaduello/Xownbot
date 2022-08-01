import hashlib
import os.path
import pickle
import tempfile
from abc import abstractmethod
from pathlib import Path
from typing import Union

from telegram import (
    Update,
    Message,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    CallbackContext,
)

from Bot.callbacks import delete_download_request
from Core.config import Settings
from Core.logger import get_logger
from Download.downloader import (
    get_downloader,
    DOWNLOADER_MAP,
    BaseDownloader,
    BaseM3U8BaseDownloader,
)
from StreamSB.ssb_client import StreamSBClient
from TeleDrive.td_client import TeleDriveClient

logger = get_logger("BOT")

DownloaderType = Union[BaseDownloader, BaseM3U8BaseDownloader]


class LoadingMessage:
    message_obj = None

    def __init__(self, original_msg, text: str):
        self.original_obj = original_msg
        self.text = text

    async def __aenter__(self):
        self.message_obj = await self.original_obj.reply_text(text=self.text)

    async def __aexit__(self, exc_type, exc_value, exc_traceback):
        await self.message_obj.delete()


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
        td_cl_ = TeleDriveClient()
        with tempfile.TemporaryDirectory() as dir_:
            file_path = os.path.join(dir_, self.downloader.file_name)
            with open(file_path, "wb") as f_:
                await self.downloader.download_video(f_)
            with open(file_path, "rb") as f_:
                file_uid = await td_cl_.upload(file=f_)
        uploaded = await td_cl_.retrieve(file_uid)
        message_id = uploaded["file"]["message_id"]
        await self.query.message.reply_to_message.reply_copy(
            Settings.BOT_STORAGE, message_id
        )


class SSBVideoDownloadHandle(BaseDownloadHandle):
    async def handle(self):
        quality = self.query.data.rsplit(":", 1)[-1]
        self.downloader.set_quality(quality)
        ssb_cl_ = StreamSBClient()
        with tempfile.TemporaryDirectory() as dir_:
            file_path = os.path.join(dir_, self.downloader.file_name)
            with open(file_path, "wb") as f_:
                await self.downloader.download_video(f_)
            with open(file_path, "rb") as f_:
                req = await ssb_cl_.upload(f_)
            file_url = ssb_cl_.get_file_url(req[0]["code"])
        await self.query.message.reply_to_message.reply_text(
            file_url, quote=True
        )


async def video_upload(update: Update, _):
    message = update.message
    td_cl = TeleDriveClient()
    ssb_cl = StreamSBClient()
    bot = update.effective_chat.get_bot()
    async with LoadingMessage(
        message,
        "please wait while fetching requested media ...",
    ):
        fwed = await bot.forward_message(
            chat_id=Settings.BOT_STORAGE,
            from_chat_id=update.effective_chat.id,
            message_id=update.message.id,
        )
        file_td = await td_cl.create(fwed.message_id)
        with tempfile.TemporaryDirectory() as dir_:
            with open(Path(dir_) / file_td["file"]["name"], "wb") as f_:
                await td_cl.download(
                    file_uid=file_td["file"]["id"], save_to=f_
                )
            with open(Path(dir_) / file_td["file"]["name"], "rb") as f_:
                ssb_file = await ssb_cl.upload(f_)
        file_url = ssb_cl.get_file_url(ssb_file[0]["code"])
    await message.reply_text(file_url, quote=True)


async def download_request(update: Update, context: CallbackContext):
    def download_options(downloader_: BaseDownloader, hash_str: str):
        def _get_kbd_sorted(qualities__):
            return sorted(qualities__, key=lambda d_: d_["size"])

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
            for x in _get_kbd_sorted(downloader_.qualities)
        ]
        kybrd__ += [
            [
                InlineKeyboardButton(
                    "StreamSB " + x["name"],
                    callback_data=f"dl:ssb:{hash_str}:{x['name']}",
                )
            ]
            for x in _get_kbd_sorted(downloader_.qualities)
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
        cache_ = _get_downloader_cache(downloader)
        if cache_:
            downloader = cache_
        else:
            await downloader.prepare()
            _set_downloader_cache(downloader)

    md_ = hashlib.md5(downloader.url.encode()).hexdigest()
    msg_, kybrd_ = download_options(downloader, md_)
    options_msg = await original_msg.reply_html(
        text=msg_, quote=True, reply_markup=kybrd_
    )
    context.chat_data[md_] = downloader
    context.job_queue.run_once(
        delete_download_request,
        Settings.BOT_AUTO_DELETE,
        chat_id=update.effective_message.chat_id,
        data=dict(msg=options_msg, hash_str=md_),
    )


def _get_downloader_cache(downloader: DownloaderType):
    md_ = hashlib.md5(downloader.url.encode()).hexdigest()
    file_ = Settings.BOT_DOWNLOADER_CACHE_PATH / md_
    if not file_.is_file():
        return
    with open(file_, "rb") as f_:
        downloader_data = pickle.load(f_)
    logger.debug(f"loading downloader from cache: {downloader_data}")
    downloader.name = downloader_data["name"]
    downloader.meta = downloader_data["meta"]
    downloader.base_content = downloader_data["base_content"]
    downloader.qualities = downloader_data["qualities"]
    downloader.image_urls = downloader_data["image_urls"]
    if isinstance(downloader, BaseM3U8BaseDownloader):
        downloader.src_list = downloader_data["src_list"]
    return downloader


def _set_downloader_cache(downloader: DownloaderType):
    md_ = hashlib.md5(downloader.url.encode()).hexdigest()
    file_ = Settings.BOT_DOWNLOADER_CACHE_PATH / md_
    downloader_data = {
        "name": downloader.name,
        "meta": downloader.meta,
        "base_content": downloader.base_content,
        "qualities": downloader.qualities,
        "image_urls": downloader.image_urls,
    }
    if isinstance(downloader, BaseM3U8BaseDownloader):
        downloader_data["src_list"] = downloader.src_list
    logger.debug(f"dumping downloader from cache: {downloader_data}")
    with open(file_, "wb") as f_:
        pickle.dump(downloader_data, f_)


image_download = ImageDownloadHandle.run
video_download = VideoDownloadHandle.run
ssb_video_download = SSBVideoDownloadHandle.run
