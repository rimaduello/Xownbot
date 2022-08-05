import hashlib
import math
import os.path
import pickle
import tempfile
from abc import abstractmethod
from functools import partial
from typing import Union

from telegram import (
    Update,
    Message,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    constants,
)
from telegram.ext import (
    CallbackContext,
)
from telegram.helpers import escape_markdown

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
        self.text = "☢ " + md_escape(text)
        self.bar = bar

    async def update_message(self, text: str):
        self.text = md_escape(text)
        await self._update_message()

    async def update_bar_absolute(self, val):
        self.bar_val = val
        await self._update_message()

    async def update_bar_relative(self, val):
        await self.update_bar_absolute(self.bar_val + val)

    async def _update_message(self):
        if self.text_w_bar != self._old_text:
            self._old_text = self.text_w_bar
            await self.message_obj.edit_text(
                self.text_w_bar, parse_mode=constants.ParseMode.MARKDOWN_V2
            )

    async def __aenter__(self):
        self._old_text = self.text_w_bar
        self.message_obj = await self.original_obj.reply_text(
            text=self.text_w_bar, parse_mode=constants.ParseMode.MARKDOWN_V2
        )

    async def __aexit__(self, exc_type, exc_value, exc_traceback):
        await self.message_obj.delete()

    @property
    def text_w_bar(self):
        t_ = self.text
        if self.bar:
            bar_shapes = math.floor(self.bar_val / 100 * self.BAR_LENGTH)
            t_ += (
                f"\n ☢ {md_escape('[')}"
                f"`{md_escape('#') * bar_shapes}{md_escape('-') * (self.BAR_LENGTH - bar_shapes)}`"
                f"{md_escape(']')} {md_escape(str(int(self.bar_val)) + '%')}"
            )
        return t_


class BaseHandler:
    auth_req: list = ["active"]

    def __init__(self, update: Update, context: CallbackContext):
        self.update = update
        self.context = context
        self.query = update.callback_query

    def auth_check(self):
        if self.auth_req:
            for k_ in self.auth_req:
                v_ = self.context.user_data.get(k_, False)
                if not v_:
                    return False
        return True

    @abstractmethod
    async def exec(self):
        raise NotImplementedError

    @classmethod
    async def run(cls, update: Update, context: CallbackContext):
        cls_ = cls(update=update, context=context)
        if cls_.auth_check():
            await cls_.exec()
        else:
            logger.warning(
                f"un-authorized request: {update.effective_user.id} ({update.effective_user.name}):"
                f"{update.message}"
            )


class BaseDownloadHandle(BaseHandler):
    downloader: BaseDownloader = None
    loading_text = "please wait while fetching requested media ..."
    loading_bar = False

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


class VideoUploadHandle(BaseHandler):
    async def exec(self):
        message = self.update.message
        logger.info(f"upload request: {message.video.file_id}")
        td_cl = TeleDriveClient()
        ssb_cl = StreamSBClient()
        bot = self.update.effective_chat.get_bot()
        async with LoadingMessage(
            message,
            "please wait while fetching requested media ...",
        ):
            fwed = await bot.forward_message(
                chat_id=Settings.BOT_STORAGE,
                from_chat_id=self.update.effective_chat.id,
                message_id=self.update.message.id,
            )
            with tempfile.TemporaryDirectory() as dir_:
                file_path_ = await td_cl.download(
                    msg_id=fwed.id, dir_path=dir_
                )
                with open(file_path_, "rb") as f_:
                    ssb_file = await ssb_cl.upload(f_)
            file_url = ssb_cl.get_file_url(ssb_file[0]["code"])
        await message.reply_text(file_url, quote=True)
        logger.info(
            f"upload request done: {self.update.message.video.file_id}"
        )


class DownloadRequestHandle(BaseHandler):
    downloader: DownloaderType = None

    def __init__(self, update: Update, context: CallbackContext):
        super(DownloadRequestHandle, self).__init__(
            update=update, context=context
        )
        self.original_msg: Message = self.update.message
        self.url = self.original_msg.text

    async def exec(self):
        async with LoadingMessage(self.original_msg, "please wait ..."):
            await self.get_or_prepare_downloader()
        if self.downloader is None:
            msg = f"this website is not supported. supported ones are {', '.join(DOWNLOADER_MAP.keys())}"
            await self.original_msg.reply_text(text=msg, quote=True)
            return
        md_ = hashlib.md5(self.downloader.url.encode()).hexdigest()
        msg_, kybrd_ = self.download_options(md_)
        options_msg = await self.original_msg.reply_text(
            text=msg_,
            quote=True,
            reply_markup=kybrd_,
            parse_mode=constants.ParseMode.MARKDOWN_V2,
        )
        self.context.chat_data[md_] = self.downloader
        self.context.job_queue.run_once(
            delete_download_request,
            Settings.BOT_AUTO_DELETE,
            chat_id=self.update.effective_message.chat_id,
            data=dict(msg=options_msg, hash_str=md_),
        )
        logger.info(f"download request done: {self.downloader.url}")

    def download_options(self, hash_str: str):
        def _get_kbd_sorted(qualities__):
            return sorted(qualities__, key=lambda d_: d_["size"])

        msg_ = f"*{md_escape(self.downloader.name)}*"
        for k_, v_ in self.downloader.meta.items():
            msg_ += f"\n⭕ _{md_escape(str(k_))}: {md_escape(str(v_))}_"
        kybrd_ = [
            [
                InlineKeyboardButton(
                    f"{x['name']}: {round(x['size'] / (1024 ** 2), 2)} MB",
                    callback_data=f"dl:video:{hash_str}:{x['name']}",
                )
            ]
            for x in _get_kbd_sorted(self.downloader.qualities)
        ]
        kybrd_ += [
            [
                InlineKeyboardButton(
                    "StreamSB " + x["name"],
                    callback_data=f"dl:ssb:{hash_str}:{x['name']}",
                )
            ]
            for x in _get_kbd_sorted(self.downloader.qualities)
        ]
        if self.downloader.image_urls:
            kybrd_.append(
                [
                    InlineKeyboardButton(
                        f"images ({len(self.downloader.image_urls)})",
                        callback_data=f"dl:image:{hash_str}",
                    )
                ]
            )
        kybrd_ = InlineKeyboardMarkup(kybrd_)
        return msg_, kybrd_

    async def get_or_prepare_downloader(self):
        logger.info(f"download request: {self.url}")
        try:
            self.downloader = get_downloader(self.url)
        except KeyError:
            logger.warning(f"unsupported website: {self.url}")
            return
        cache_ = self._get_downloader_cache()
        if cache_:
            pass
        else:
            await self.downloader.prepare()
            self._set_downloader_cache()

    def _get_downloader_cache(self):
        md_ = hashlib.md5(self.downloader.url.encode()).hexdigest()
        file_ = Settings.BOT_DOWNLOADER_CACHE_PATH / md_
        if not file_.is_file():
            logger.debug(f"downloader cache not found: {md_}")
            return False
        with open(file_, "rb") as f_:
            downloader_data = pickle.load(f_)
        logger.debug(f"loading downloader from cache: {downloader_data}")
        self.downloader.name = downloader_data["name"]
        self.downloader.meta = downloader_data["meta"]
        self.downloader.base_content = downloader_data["base_content"]
        self.downloader.qualities = downloader_data["qualities"]
        self.downloader.image_urls = downloader_data["image_urls"]
        if isinstance(self.downloader, BaseM3U8BaseDownloader):
            self.downloader.src_list = downloader_data["src_list"]
        return True

    def _set_downloader_cache(self):
        md_ = hashlib.md5(self.downloader.url.encode()).hexdigest()
        file_ = Settings.BOT_DOWNLOADER_CACHE_PATH / md_
        downloader_data = {
            "name": self.downloader.name,
            "meta": self.downloader.meta,
            "base_content": self.downloader.base_content,
            "qualities": self.downloader.qualities,
            "image_urls": self.downloader.image_urls,
        }
        if isinstance(self.downloader, BaseM3U8BaseDownloader):
            downloader_data["src_list"] = self.downloader.src_list
        logger.debug(f"dumping self.downloader cache: {downloader_data}")
        with open(file_, "wb") as f_:
            pickle.dump(downloader_data, f_)


async def user_auth(update: Update, context: CallbackContext):
    async def _is_authed(uid__):
        return await Mongo.get_collection(
            Settings.MONGO_COLLECTION_USER
        ).find_one({"user_id": str(uid__), "active": True})

    u_ = await _is_authed(update.effective_user.id)
    if u_:
        context.user_data["active"] = u_["active"]


async def dummy(_, __):
    return


md_escape = partial(escape_markdown, version=2)

image_download = ImageDownloadHandle.run
video_download = VideoDownloadHandle.run
ssb_video_download = SSBVideoDownloadHandle.run
video_upload = VideoUploadHandle.run
download_request = DownloadRequestHandle.run
