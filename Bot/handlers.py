# todo: pending jobs on startup

from __future__ import annotations

import hashlib
import logging
import math
import os.path
import tempfile
from abc import abstractmethod, ABC
from functools import partial
from io import BytesIO
from logging import Logger
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
from Core.logger import get_logger, call_log
from Download.downloader import (
    get_downloader,
    DOWNLOADER_MAP,
    BaseDownloader,
    BaseM3U8Downloader,
    Source,
)
from FileServer.file_server import FileObj, FileResultType
from TeleDrive.td_client import TeleDriveClient
from utils.helpers import size_hr

logger = get_logger(__name__)

DownloaderType = Union[BaseDownloader, BaseM3U8Downloader]


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


class BaseHandler(ABC):
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

    @classmethod
    @call_log(logger)
    async def run(
        cls, update: Update, context: CallbackContext, _function_logger
    ):
        cls_ = cls(update=update, context=context)
        if cls_.auth_check():
            await cls_.exec(_function_logger)
        else:
            _function_logger.warning(
                f"un-authorized request: {update.effective_user.id} ({update.effective_user.name}):"
                f"{update.message}"
            )

    @abstractmethod
    async def exec(self, _function_logger):
        raise NotImplementedError

    def _log(self, _logger: Logger, level, msg):
        id_ = self.update.message or self.update.callback_query
        id_ = id_.id
        type_ = "message" if self.update.message else "query"
        _logger = _logger.getChild(f"{type_}={id_}")
        _logger.log(level, msg)


class BaseRequestHandler(BaseHandler, ABC):
    query_prefix: str

    async def exec(self, _function_logger):
        req_arg_ = await self.req_arg_gen()
        if not req_arg_:
            self._log(
                _function_logger,
                logging.WARNING,
                f"request filed: {self.message} didn't yield any request arg",
            )
            return
        self._log(_function_logger, logging.INFO, f"request_args={req_arg_}")
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

    @staticmethod
    @call_log(logger)
    async def cleanup(context: CallbackContext):
        data = context.job.data
        await data["msg"].delete()

    @classmethod
    def _query_str(cls, req, *req_arg):
        return (
            f"{cls.query_prefix}:{req}:{':'.join([str(x) for x in req_arg])}"
        )

    @abstractmethod
    def query_options(self, req_arg: str) -> (str, InlineKeyboardMarkup):
        raise NotImplementedError

    @abstractmethod
    async def req_arg_gen(self):
        raise NotImplementedError


class BaseQueryHandler(BaseHandler, ABC):
    loading_bar = None
    image_reqs = ["image"]
    video_reqs = ["tg", "direct"]

    def __init__(self, update: Update, context: CallbackContext):
        super().__init__(update, context)
        self.query_data = self.query.data.split(":")
        self.req_type = self.query_data[0]
        self.req = self.query_data[1]
        self.req_arg = self.query_data[2]
        src = self.query_data[3] if len(self.query_data) == 4 else None
        self.source_index = None if src is None else int(src)

    async def exec(self, _function_logger):
        self.loading_bar = LoadingMessage(
            self.query.message, f"{self.file_name}\nDownloading ...", bar=False
        )
        await self.query.answer()
        async with self.loading_bar:
            if self.req in self.image_reqs:
                await self.image_req()
            if self.req in self.video_reqs:
                await self.video_req()

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
    @call_log(logger)
    async def run(
        cls,
        update: Update,
        context: CallbackContext,
        _function_logger,
        mix=True,
    ):
        if mix:
            req = update.callback_query.data.split(":")[1]
            mix_with = {
                "image": ToTGMixin,
                "tg": ToTGMixin,
                "direct": ToDirectMixin,
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
        msg_ = f"*{md_escape(self.downloader.name)}*"
        for k_, v_ in self.downloader.metadata.items():
            msg_ += f"\n⭕ _{md_escape(str(k_))}: {md_escape(str(v_))}_"
        x: Source
        kybrd_ = [
            [
                InlineKeyboardButton(
                    f"{x}",
                    callback_data=self._query_str("tg", req_arg, c_),
                )
            ]
            for c_, x in enumerate(self.downloader.source_list)
        ]
        kybrd_ += [
            [
                InlineKeyboardButton(
                    f"Direct {x}",
                    callback_data=self._query_str("direct", req_arg, c_),
                )
            ]
            for c_, x in enumerate(self.downloader.source_list)
        ]
        if self.downloader.image_list:
            kybrd_.append(
                [
                    InlineKeyboardButton(
                        f"images ({len(self.downloader.image_list)})",
                        callback_data=self._query_str("image", req_arg),
                    )
                ]
            )
        kybrd_ = InlineKeyboardMarkup(kybrd_)
        return msg_, kybrd_

    @staticmethod
    @call_log(logger)
    async def cleanup(context: CallbackContext):
        await BaseRequestHandler.cleanup(context)
        data = context.job.data
        context.chat_data.pop(data["req_arg"], None)

    @call_log(logger)
    async def get_or_prepare_downloader(self, _function_logger):
        try:
            self.downloader = get_downloader(self.url)
        except KeyError:
            self._log(
                _function_logger,
                logging.WARNING,
                f"unsupported website: {self.url}",
            )
            return
        self.downloader.load(not_exist_ok=True)
        if not self.downloader.is_prepared:
            await self.downloader.prepare()
            self.downloader.save()


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
        msg_ += f"__{md_escape(size_hr(self.message.video.file_size))}__"
        kybrd_ = [
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

    @call_log(logger)
    async def image_req(self, _function_logger):
        self._log(
            _function_logger,
            logging.INFO,
            f"image request: {self.file_name}({self.downloader.md_hash})",
        )
        self.loading_bar.bar = False
        for c_, src_ in enumerate(self.downloader.image_list):
            with tempfile.TemporaryFile() as f_:
                await self.downloader.download_image(f_, c_)
                f_.seek(0)
                filename = src_.rsplit("/")[-1]
                await self.handle(f_, filename)

    @call_log(logger)
    async def video_req(self, _function_logger):
        self._log(
            _function_logger,
            logging.INFO,
            f"video request: {self.file_name}({self.downloader.md_hash})",
        )
        self.loading_bar.bar = True
        with tempfile.TemporaryDirectory() as dir_:
            file_path = os.path.join(dir_, self.downloader.file_name)
            with open(file_path, "wb") as f_:
                await self.downloader.download_video(
                    self.source_index, f_, self._update_loading_bar
                )
                f_.seek(0)
                filename = self.downloader.file_name
                await self.handle(f_, filename)

    @property
    def file_name(self):
        msg = [self.downloader.name]
        if self.source_index is not None:
            msg.append(self.downloader.source_list[self.source_index].name)
        msg.append(f"({self.req})")
        return " ".join(msg)

    @abstractmethod
    async def handle(self, media: Union[BytesIO, BinaryIO], file_name=None):
        pass

    async def _update_loading_bar(self, total, rel):
        await self.loading_bar.update_bar_relative(rel / total * 100)


class MediaQueryHandle(BaseQueryHandler):
    async def image_req(self):
        raise NotImplementedError

    @call_log(logger)
    async def video_req(self, _function_logger):
        self._log(
            _function_logger, logging.INFO, f"video request: {self.file_name}"
        )
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
        file_name = file_name or Path(media.name).name
        if self.req in self.image_reqs:
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
            uploaded = await td_cl_.upload(media.name)
            await self.query.message.reply_to_message.reply_copy(
                Settings.BOT_STORAGE, uploaded.id
            )


class ToDirectMixin:
    async def handle(
        self: Type[BaseQueryHandler, ToDirectMixin],
        media: Union[BytesIO, BinaryIO],
        _,
    ):
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
    @call_log(logger)
    async def cleanup(context: CallbackContext):
        data = context.job.data
        file_cl_ = await FileObj.user(data["user_id"])
        file_cl_.del_file(data["file_name"])
        await data["msg"].delete()


class FileListHandle(BaseHandler):
    @staticmethod
    def _report(_f: FileResultType):
        name = f"[*{escape_markdown(_f['name'], version=2)}*]({_f['url']})"
        size = f"__{escape_markdown(str(_f['size']), version=2)}__"
        ttl = _f["created"] + Settings.FILESERVER_AUTO_DELETE - time()
        ttl = str(int(ttl))
        ttl = f"_{md_escape(ttl)} seconds_"
        return f"➡ {name}\n{size}\n{ttl}\n"

    async def exec(self, _function_logger):
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
