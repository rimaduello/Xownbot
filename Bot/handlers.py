# todo: pending jobs on startup

from __future__ import annotations
import hashlib
import math
import os.path
import pickle
import tempfile
from abc import abstractmethod, ABC
from functools import partial
from io import BytesIO
from pathlib import Path
from time import time
from typing import Union, BinaryIO, Type

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

from Core.config import Settings
from Core.db import Mongo
from Core.logger import get_logger
from Download.downloader import (
    get_downloader,
    DOWNLOADER_MAP,
    BaseDownloader,
    BaseM3U8BaseDownloader,
)
from FileServer.file_server import FileObj, FileResultType
from StreamSB.ssb_client import StreamSBClient
from TeleDrive.td_client import TeleDriveClient

logger = get_logger("BOT")

DownloaderType = Union[BaseDownloader, BaseM3U8BaseDownloader]


class LoadingMessage:
    BAR_LENGTH = 10
    message_obj = None
    bar_val = 0
    _old_text = None

    def __init__(
        self,
        original_msg: Message,
        text: str,
        bar: bool = False,
        prefix_icon="☢",
    ):
        self.original_obj = original_msg
        self.prefix_icon = prefix_icon
        self.text = f"{self.prefix_icon} {text}"
        self.bar = bar

    async def update_message(self, text: str):
        self.text = (
            "" if text.startswith(self.prefix_icon) else f"{self.prefix_icon} "
        ) + text
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
        t_ = md_escape(self.text)
        if self.bar:
            bar_shapes = math.floor(self.bar_val / 100 * self.BAR_LENGTH)
            t_ += (
                f"\n{md_escape('[')}"
                f"`{md_escape('#') * bar_shapes}{md_escape('-') * (self.BAR_LENGTH - bar_shapes)}`"
                f"{md_escape(']')} {md_escape(str(int(self.bar_val)) + '%')}"
            )
        return t_


class BaseHandler:
    auth_req: list = ["active"]

    def __init__(self, update: Update, context: CallbackContext):
        self.update = update
        self.context = context
        self.bot = context.bot
        self.query = update.callback_query
        self.message = update.message
        self.user = update.effective_user
        self.user_id = update.effective_user.id

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


class BaseRequestHandler(BaseHandler, ABC):
    query_prefix: str

    async def exec(self):
        req_arg_ = await self.req_arg_gen()
        if not req_arg_:
            logger.warning(
                f"request filed: {self.message} didn't yield any request arg"
            )
            return
        msg_, kybrd_ = self.query_options(req_arg_)
        options_msg = await self.message.reply_text(
            text=msg_,
            quote=True,
            reply_markup=kybrd_,
            parse_mode=constants.ParseMode.MARKDOWN_V2,
        )
        self.context.job_queue.run_once(
            self.cleanup,
            Settings.BOT_AUTO_DELETE,
            chat_id=self.update.effective_message.chat_id,
            data=dict(msg=options_msg, req_arg=req_arg_),
        )
        logger.info(f"request done: {self.message} for {req_arg_}")

    @staticmethod
    async def cleanup(context: CallbackContext):
        data = context.job.data
        await data["msg"].delete()
        logger.info(f"cleaned up: {data['req_arg']}")

    @classmethod
    def _query_str(cls, req, req_arg, quality=None):
        return f"{cls.query_prefix}:{req}:{req_arg}" + (
            f":{quality}" if quality else ""
        )

    @abstractmethod
    def query_options(self, req_arg: str) -> (str, InlineKeyboardMarkup):
        raise NotImplementedError

    @abstractmethod
    async def req_arg_gen(self):
        raise NotImplementedError


class BaseQueryHandler(BaseHandler):
    loading_bar = None
    image_reqs = ["image"]
    video_reqs = ["tg", "direct", "ssb"]

    def __init__(self, update: Update, context: CallbackContext):
        super().__init__(update, context)
        self.query_data = self.query.data.split(":")
        self.req_type = self.query_data[0]
        self.req = self.query_data[1]
        self.req_arg = self.query_data[2]
        self.quality = (
            self.query_data[3] if len(self.query_data) == 4 else None
        )

    async def exec(self):
        logger.info(f"query request: {self.file_name}")
        self.loading_bar = LoadingMessage(
            self.query.message, f"{self.file_name}\nDownloading ...", bar=False
        )
        await self.query.answer()
        async with self.loading_bar:
            if self.req in self.image_reqs:
                await self.image_req()
            if self.req in self.video_reqs:
                await self.video_req()
        logger.info(f"query request done: {self.file_name}")

    @abstractmethod
    async def image_req(self):
        raise NotImplementedError

    @abstractmethod
    async def video_req(self):
        raise NotImplementedError

    @property
    @abstractmethod
    def file_name(self):
        raise NotImplementedError

    @abstractmethod
    async def handle(self, media: Union[BytesIO, BinaryIO], file_name=None):
        raise NotImplementedError

    @classmethod
    async def run(cls, update: Update, context: CallbackContext, mix=True):
        if mix:
            req = update.callback_query.data.split(":")[1]
            mix_with = {
                "image": ToTGMixin,
                "tg": ToTGMixin,
                "direct": ToDirectMixin,
                "ssb": ToSSBMixin,
            }[req]
            cls_ = type(f"url_{req}_handler", (mix_with, cls), {})
            # noinspection PyUnresolvedReferences
            return await cls_.run(update=update, context=context, mix=False)
        else:
            return await super(BaseQueryHandler, cls).run(
                update=update, context=context
            )


class UrlRequestHandle(BaseRequestHandler):
    query_prefix = "u"
    downloader: DownloaderType = None

    def __init__(self, update: Update, context: CallbackContext):
        super(UrlRequestHandle, self).__init__(update=update, context=context)
        self.url = self.message.text

    async def req_arg_gen(self):
        async with LoadingMessage(self.message, "please wait ..."):
            await self.get_or_prepare_downloader()
        if self.downloader is None:
            msg = f"this website is not supported. supported ones are {', '.join(DOWNLOADER_MAP.keys())}"
            await self.message.reply_text(text=msg, quote=True)
            return
        md_ = hashlib.md5(self.downloader.url.encode()).hexdigest()
        self.context.chat_data[md_] = self.downloader
        return md_

    def query_options(self, req_arg: str):
        def _get_kbd_sorted(qualities__):
            return sorted(qualities__, key=lambda d_: d_["size"])

        msg_ = f"*{md_escape(self.downloader.name)}*"
        for k_, v_ in self.downloader.meta.items():
            msg_ += f"\n⭕ _{md_escape(str(k_))}: {md_escape(str(v_))}_"
        kybrd_ = [
            [
                InlineKeyboardButton(
                    f"{x['name']}: {FileObj.size_hr(x['size'])}",
                    callback_data=self._query_str("tg", req_arg, x["name"]),
                )
            ]
            for x in _get_kbd_sorted(self.downloader.qualities)
        ]
        kybrd_ += [
            [
                InlineKeyboardButton(
                    "StreamSB " + x["name"],
                    callback_data=self._query_str("ssb", req_arg, x["name"]),
                )
            ]
            for x in _get_kbd_sorted(self.downloader.qualities)
        ]
        kybrd_ += [
            [
                InlineKeyboardButton(
                    "Direct " + x["name"],
                    callback_data=self._query_str(
                        "direct", req_arg, x["name"]
                    ),
                )
            ]
            for x in _get_kbd_sorted(self.downloader.qualities)
        ]
        if self.downloader.image_urls:
            kybrd_.append(
                [
                    InlineKeyboardButton(
                        f"images ({len(self.downloader.image_urls)})",
                        callback_data=self._query_str("image", req_arg),
                    )
                ]
            )
        kybrd_ = InlineKeyboardMarkup(kybrd_)
        return msg_, kybrd_

    @staticmethod
    async def cleanup(context: CallbackContext):
        await BaseRequestHandler.cleanup(context)
        data = context.job.data
        context.chat_data.pop(data["req_arg"], None)

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


class MediaRequestHandle(BaseRequestHandler):
    query_prefix = "m"

    async def req_arg_gen(self):
        fwed = await self.bot.forward_message(
            chat_id=Settings.BOT_STORAGE,
            from_chat_id=self.update.effective_chat.id,
            message_id=self.message.id,
        )
        return fwed.id

    def query_options(self, req_arg: str) -> (str, InlineKeyboardMarkup):
        msg_ = f"*{md_escape(self.message.video.file_name)}*\n"
        msg_ += f"__{md_escape(FileObj.size_hr(self.message.video.file_size * 1024))}__"
        kybrd_ = [
            [
                InlineKeyboardButton(
                    "StreamSB",
                    callback_data=self._query_str("ssb", req_arg),
                )
            ],
            [
                InlineKeyboardButton(
                    "Direct link",
                    callback_data=self._query_str("direct", req_arg),
                )
            ],
        ]
        kybrd_ = InlineKeyboardMarkup(kybrd_)
        return msg_, kybrd_


class UrlQueryHandle(BaseQueryHandler):
    def __init__(self, update: Update, context: CallbackContext):
        super().__init__(update, context)
        self.downloader: BaseDownloader = context.chat_data[self.req_arg]

    async def image_req(self):
        self.loading_bar.bar = False
        for c_, src_ in enumerate(self.downloader.image_urls):
            with tempfile.TemporaryFile() as f_:
                await self.downloader.download_image(f_, c_)
                f_.seek(0)
                filename = src_.rsplit("/")[-1]
                return await self.handle(f_, filename)

    async def video_req(self):
        self.loading_bar.bar = True
        self.downloader.set_quality(self.quality)
        with tempfile.TemporaryDirectory() as dir_:
            file_path = os.path.join(dir_, self.downloader.file_name)
            with open(file_path, "wb") as f_:
                await self.downloader.download_video(
                    f_, self._update_loading_bar
                )
                f_.seek(0)
                filename = self.downloader.file_name
                return await self.handle(f_, filename)

    @property
    def file_name(self):
        return f"{self.downloader.name} ({self.quality or self.req})"

    @abstractmethod
    async def handle(self, media: Union[BytesIO, BinaryIO], file_name=None):
        pass

    async def _update_loading_bar(self, total, rel):
        await self.loading_bar.update_bar_relative(rel / total * 100)


class MediaQueryHandle(BaseQueryHandler):
    async def image_req(self):
        raise NotImplementedError

    async def video_req(self):
        with tempfile.TemporaryDirectory() as dir_:
            td_cl = TeleDriveClient()
            file_path = await td_cl.download(
                msg_id=int(self.req_arg), dir_path=dir_
            )
            with open(file_path, "rb") as f_:
                await self.handle(f_, self.file_name)

    @property
    def file_name(self):
        return self.query.message.reply_to_message.video.file_name

    @abstractmethod
    async def handle(self, media: Union[BytesIO, BinaryIO], file_name=None):
        pass


class ToTGMixin:
    async def handle(
        self: BaseQueryHandler, media: Union[BytesIO, BinaryIO], file_name=None
    ):
        logger.info(f"uploading to telegram: {media.name}")
        file_name = file_name or Path(media.name).name
        if self.req in self.image_reqs:
            logger.debug(f"uploading image to tg: {media.name}")
            await self.query.message.reply_to_message.reply_document(
                media, filename=file_name, quote=True
            )
        elif self.req in self.video_reqs:
            td_cl_ = TeleDriveClient()
            self.loading_bar.bar = False
            await self.loading_bar.update_message(
                self.loading_bar.text.split("\n", 1)[0]
                + "\nuploading to telegram ..."
            )
            logger.debug(f"uploading video to tg: {media.name}")
            uploaded = await td_cl_.upload(media.name)
            await self.query.message.reply_to_message.reply_copy(
                Settings.BOT_STORAGE, uploaded.id
            )


class ToSSBMixin:
    async def handle(
        self: BaseQueryHandler, media: Union[BytesIO, BinaryIO], file_name=None
    ):
        logger.info(f"uploading to ssb: {media.name}")
        file_name = file_name or Path(media.name).name
        ssb_cl_ = StreamSBClient()
        self.loading_bar.bar = False
        await self.loading_bar.update_message(
            self.loading_bar.text.split("\n", 1)[0]
            + "\nuploading to StreamSB ..."
        )
        with open(media.name, "rb") as media_:
            req = await ssb_cl_.upload(media_, file_name=file_name)
        file_url = ssb_cl_.get_file_url(req[0]["code"])
        msg_ = (
            f"*{md_escape('StreamSB:')} *[{md_escape(file_name)}]({file_url})"
        )
        await self.query.message.reply_to_message.reply_text(
            msg_, quote=True, parse_mode=constants.ParseMode.MARKDOWN_V2
        )


class ToDirectMixin:
    async def handle(
        self: Type[BaseQueryHandler, ToDirectMixin],
        media: Union[BytesIO, BinaryIO],
        _,
    ):
        logger.info(f"making direct link: {media.name}")
        file_cl_ = await FileObj.user(self.user_id)
        self.loading_bar.bar = False
        await self.loading_bar.update_message(
            self.loading_bar.text.split("\n", 1)[0]
            + "\ngenerating direct link ..."
        )
        path_read = Path(media.name)
        url_ = await file_cl_.save_file(path_read)
        msg_ = f"*{md_escape('direct link:')} *[{md_escape(path_read.name)}]({url_})"
        msg_ = await self.query.message.reply_to_message.reply_text(
            msg_, quote=True, parse_mode=constants.ParseMode.MARKDOWN_V2
        )
        self.context.job_queue.run_once(
            self.cleanup,
            Settings.FILESERVER_AUTO_DELETE,
            chat_id=self.update.effective_message.chat_id,
            data=dict(
                user_id=self.user_id, file_name=path_read.name, msg=msg_
            ),
        )

    @staticmethod
    async def cleanup(context: CallbackContext):
        data = context.job.data
        file_cl_ = await FileObj.user(data["user_id"])
        file_cl_.del_file(data["file_name"])
        await data["msg"].delete()
        logger.info(f"cleaned up: {data}")


class FileListHandle(BaseHandler):
    @staticmethod
    def _report(_f: FileResultType):
        name = f"[*{escape_markdown(_f['name'], version=2)}*]({_f['url']})"
        size = f"__{escape_markdown(str(_f['size']), version=2)}__"
        ttl = _f["created"] + Settings.FILESERVER_AUTO_DELETE - time()
        ttl = str(int(ttl))
        ttl = f"_{md_escape(ttl)} seconds_"
        return f"➡ {name}\n{size}\n{ttl}\n"

    async def exec(self):
        u_ = self.user_id
        fs_ = await FileObj.user(u_)
        ls_ = fs_.list_files()
        show_ = [self._report(x) for x in ls_]
        await self.message.reply_text(
            text="\n".join(show_), parse_mode=constants.ParseMode.MARKDOWN_V2
        )


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

url_request = UrlRequestHandle.run
media_request = MediaRequestHandle.run
url_query = UrlQueryHandle.run
media_query = MediaQueryHandle.run
file_list = FileListHandle.run
