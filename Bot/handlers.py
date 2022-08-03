import hashlib
import math
import os.path
import pickle
import tempfile
from abc import abstractmethod
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
from Core.db import Mongo
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
    BAR_LENGTH = 10
    message_obj = None
    bar_val = 0
    _old_text = None

    def __init__(self, original_msg: Message, text: str, bar: bool = False):
        self.original_obj = original_msg
        self.text = text
        self.bar = bar

    async def update_message(self, text: str):
        self.text = text
        await self._update_message()

    async def update_bar_absolute(self, val):
        self.bar_val = val
        await self._update_message()

    async def update_bar_relative(self, val):
        await self.update_bar_absolute(self.bar_val + val)

    async def _update_message(self):
        if self.text_w_bar != self._old_text:
            self._old_text = self.text_w_bar
            await self.message_obj.edit_text(self.text_w_bar)

    async def __aenter__(self):
        self._old_text = self.text_w_bar
        self.message_obj = await self.original_obj.reply_text(
            text=self.text_w_bar
        )

    async def __aexit__(self, exc_type, exc_value, exc_traceback):
        await self.message_obj.delete()

    @property
    def text_w_bar(self):
        t_ = self.text
        if self.bar:
            bar_shapes = math.floor(self.bar_val / 100 * self.BAR_LENGTH)
            t_ += f"\n[{'#' * bar_shapes}{'-' * (self.BAR_LENGTH - bar_shapes)}] {int(self.bar_val)}%"
        return t_


class BaseDownloadHandle:
    downloader: BaseDownloader = None
    loading_text = "please wait while fetching requested media ..."
    loading_bar = False

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
        lb_ = LoadingMessage(
            self.query.message, self.loading_text, bar=self.loading_bar
        )
        async with lb_:
            await self.handle(loading_bar=lb_)
        logger.info(f"download request done: {query.data}")

    @classmethod
    async def run(cls, update: Update, context: CallbackContext):
        cls_ = cls(update=update, context=context)
        await cls_.exec()

    @abstractmethod
    async def handle(self, loading_bar: LoadingMessage):
        pass


class ImageDownloadHandle(BaseDownloadHandle):
    async def handle(self, loading_bar):
        for c_, src_ in enumerate(self.downloader.image_urls):
            with tempfile.TemporaryFile() as f_:
                await self.downloader.download_image(f_, c_)
                f_.seek(0)
                filename = src_.rsplit("/")[-1]
                await self.query.message.reply_to_message.reply_document(
                    f_, filename=filename, quote=True
                )


class VideoDownloadHandle(BaseDownloadHandle):
    loading_bar = True

    @staticmethod
    def update_bar_download_factory(msg: LoadingMessage):
        async def _fn(total, rel):
            await msg.update_bar_relative(rel / total * 100)

        return _fn

    async def handle(self, loading_bar):
        quality = self.query.data.rsplit(":", 1)[-1]
        self.downloader.set_quality(quality)
        l_title = f"{self.downloader.name} ({quality})"
        await loading_bar.update_message(f"{l_title}\nDownloading ...")
        td_cl_ = TeleDriveClient()
        with tempfile.TemporaryDirectory() as dir_:
            file_path = os.path.join(dir_, self.downloader.file_name)
            with open(file_path, "wb") as f_:
                await self.downloader.download_video(
                    f_, self.update_bar_download_factory(loading_bar)
                )
            loading_bar.bar = False
            await loading_bar.update_message(
                f"{l_title}\nUploading to telegram ..."
            )
            uploaded = await td_cl_.upload(file_path)
        await self.query.message.reply_to_message.reply_copy(
            Settings.BOT_STORAGE, uploaded.id
        )


class SSBVideoDownloadHandle(VideoDownloadHandle):
    async def handle(self, loading_bar):
        quality = self.query.data.rsplit(":", 1)[-1]
        self.downloader.set_quality(quality)
        l_title = f"{self.downloader.name} ({quality})"
        await loading_bar.update_message(f"{l_title}\nDownloading ...")
        ssb_cl_ = StreamSBClient()
        with tempfile.TemporaryDirectory() as dir_:
            file_path = os.path.join(dir_, self.downloader.file_name)
            with open(file_path, "wb") as f_:
                await self.downloader.download_video(
                    f_, self.update_bar_download_factory(loading_bar)
                )
            loading_bar.bar = False
            await loading_bar.update_message(
                f"{l_title}\nUploading to StreamSB ..."
            )
            with open(file_path, "rb") as f_:
                req = await ssb_cl_.upload(f_)
            file_url = ssb_cl_.get_file_url(req[0]["code"])
        await self.query.message.reply_to_message.reply_text(
            file_url, quote=True
        )


async def video_upload(update: Update, _):
    message = update.message
    logger.info(f"upload request: {message.video.file_id}")
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
        with tempfile.TemporaryDirectory() as dir_:
            file_path_ = await td_cl.download(msg_id=fwed.id, dir_path=dir_)
            with open(file_path_, "rb") as f_:
                ssb_file = await ssb_cl.upload(f_)
        file_url = ssb_cl.get_file_url(ssb_file[0]["code"])
    await message.reply_text(file_url, quote=True)
    logger.info(f"upload request done: {update.message.video.file_id}")


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
    logger.info(f"download request: {url}")
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
    logger.info(f"download request done: {url}")


async def user_check(update: Update, context: CallbackContext):
    async def _is_authed(uid__):
        return await Mongo.get_collection(
            Settings.MONGO_COLLECTION_USER
        ).find_one({"user_id": str(uid__), "active": True})

    u_ = await _is_authed(update.effective_user.id)
    if u_:
        context.user_data["active"] = True
    else:
        context.user_data["active"] = False
    update.effective_user.is_premium = u_


async def unauthorised(update: Update, _):
    logger.warning(
        f"un-authorized request: {update.effective_user.id} ({update.effective_user.name}):"
        f"{update.message}"
    )
    return


async def dummy(_, __):
    return


def _get_downloader_cache(downloader: DownloaderType):
    md_ = hashlib.md5(downloader.url.encode()).hexdigest()
    file_ = Settings.BOT_DOWNLOADER_CACHE_PATH / md_
    if not file_.is_file():
        logger.debug(f"downloader cache not found: {md_}")
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
    logger.debug(f"dumping downloader cache: {downloader_data}")
    with open(file_, "wb") as f_:
        pickle.dump(downloader_data, f_)


image_download = ImageDownloadHandle.run
video_download = VideoDownloadHandle.run
ssb_video_download = SSBVideoDownloadHandle.run
