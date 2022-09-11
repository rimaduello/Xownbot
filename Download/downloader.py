from __future__ import annotations

import asyncio
import hashlib
import inspect
import logging
import os
import pickle
import random
import re
import shutil
import tempfile
import urllib.parse
from abc import ABC, abstractmethod
from contextlib import contextmanager
from logging import Logger
from pathlib import Path
from statistics import mean
from typing import List, Tuple, Optional, Union

import aiofiles
import isodate
import m3u8
from bs4 import BeautifulSoup
from m3u8 import M3U8
from pydantic import BaseModel, HttpUrl

from Core.config import Settings
from Core.logger import get_logger, call_log
from Download.exception import NotSupportedSite, NotSupportedFile
from Download.helpers import tpc__decode, tpc__detail
from Download.http import AioHttpClient, Aria2Client
from utils.helpers import size_hr

logger = get_logger(__name__)


class Source(BaseModel):
    name: str
    url: HttpUrl
    size: int
    seg: List[HttpUrl]

    def __str__(self):
        return f"{self.name}: {size_hr(self.size)}"


class BaseDownloader(ABC):
    name: str
    metadata: dict
    md_hash: str
    base_content: bytes
    base_bs4: BeautifulSoup
    _source_list: List[Source]
    image_list: List[HttpUrl]
    _src: Optional[Source]
    META = [
        "url",
        "name",
        "md_hash",
        "metadata",
        "_source_list",
        "image_list",
    ]

    def __init__(self, url):
        self.url = url
        self.metadata = {}
        self.md_hash = hashlib.md5(url.encode()).hexdigest()
        self.http_session = AioHttpClient()
        self.aria2_session = Aria2Client()
        self._source_list = []
        self.image_list = []
        self._prepared = False
        self._src = None

    @call_log(logger)
    async def prepare(self, _function_logger):
        self.base_content, self.base_bs4 = await self.prepare__base_content()
        self._source_list = await self.prepare__source_list()
        self.image_list = await self.prepare__image_list()
        self.name = await self.prepare__name()
        self.metadata = await self.prepare__metadata()
        self._prepared = True
        self._log(
            _function_logger, logging.DEBUG, f"preparation result: {self}"
        )

    @call_log(logger)
    async def download_video(
        self, src_index: int, save_path: Path, update_fn=None
    ):
        with self.set_src(src_index):
            with aria2_temp_dir() as dir_:
                dir_path = Path(dir_)
                async with self.aria2_session.with_download(
                    url=self._src.url,
                    update_fn=update_fn,
                    save_dir=dir_path,
                ) as dl_:
                    await self.copy_file(dir_path / dl_.name, save_path)

    @call_log(logger)
    async def download_image(self, save_path: Path, i):
        with aria2_temp_dir() as dir_:
            dir_path = Path(dir_)
            async with self.aria2_session.with_download(
                url=self.image_list[i], save_dir=dir_path
            ) as dl_:
                await self.copy_file(dir_path / dl_.name, save_path)

    @call_log(logger)
    def save(self, _function_logger):
        meta_ = {}
        file_ = self.cache_path
        for m_ in self.META:
            meta_[m_] = getattr(self, m_)
        self._log(_function_logger, logging.DEBUG, f"meta:{meta_}")
        with open(file_, "wb") as f_:
            pickle.dump(meta_, f_)

    @call_log(logger)
    def load(self, _function_logger, not_exist_ok=True):
        file_ = self.cache_path
        if not file_.is_file():
            msg = "cache not found"
            if not not_exist_ok:
                self._log(_function_logger, logging.ERROR, msg)
                raise FileNotFoundError
            self._log(_function_logger, logging.WARNING, msg)
            return
        with open(file_, "rb") as f_:
            meta_ = pickle.load(f_)
        self._log(_function_logger, logging.DEBUG, f"meta:{meta_}")
        for m_ in self.META:
            setattr(self, m_, meta_[m_])
        self._prepared = True

    @contextmanager
    def set_src(self, src_index):
        self._src = self.source_list[src_index]
        try:
            yield
        finally:
            self._src = None

    @call_log(logger)
    async def get_size(self, src: HttpUrl):
        async with self.http_session.head(
            url=src, allow_redirects=True
        ) as req:
            return req.content_length

    @staticmethod
    async def copy_file(src: Path, target: Path):
        await asyncio.to_thread(shutil.copyfile, src, target)

    async def prepare__base_content(
        self,
    ) -> Tuple[BaseDownloader.base_content, BaseDownloader.base_bs4]:
        async with self.http_session.get(url=self.url) as data_:
            content = await data_.read()
        return content, BeautifulSoup(content, "html.parser")

    @abstractmethod
    async def prepare__source_list(self) -> BaseDownloader.source_list:
        pass

    @abstractmethod
    async def prepare__image_list(self) -> BaseDownloader.image_list:
        pass

    @abstractmethod
    async def prepare__name(self) -> BaseDownloader.name:
        pass

    @abstractmethod
    async def prepare__metadata(self) -> BaseDownloader.metadata:
        pass

    def _log(self, _logger: Logger, level, msg):
        _logger = _logger.getChild(f"md5={self.md_hash}")
        _logger.log(level, msg)

    @property
    def file_name(self):
        return f"{self.name}.mp4"

    @property
    def cache_path(self):
        return Settings.DOWNLOADER_SAVE_PATH / self.md_hash

    @property
    def is_prepared(self):
        return self._prepared

    @property
    def source_list(self):
        return sorted(self._source_list, key=lambda d_: d_.size)

    def __str__(self):
        n_ = f"{self.url}: "
        if self.is_prepared:
            n_ += (
                f"name={self.name} md={self.md_hash} metadata={self.metadata} "
                f"image_list={self.image_list} source_list={self.source_list}"
            )
        else:
            n_ += "not prepared"
        return n_


class BaseM3U8Downloader(BaseDownloader, ABC):
    SIZE_ESTIMATE_SAMPLE = 10

    @call_log(logger)
    async def get_m3u8_src(self, url, base_url=None):
        async with self.http_session.get(url=url) as data_:
            src_raw = await data_.text()
        return m3u8.loads(src_raw, base_url)

    @call_log(logger)
    async def get_size(self, src: Union[HttpUrl, m3u8]):
        if not isinstance(src, M3U8):
            src = await self.get_m3u8_src(src)
        seg = src.segments
        samples = (
            random.sample(seg, self.SIZE_ESTIMATE_SAMPLE)
            if len(seg) > self.SIZE_ESTIMATE_SAMPLE
            else seg
        )
        size = []
        async for c_, req in self.http_session.head_many(
            urls=[x.absolute_uri for x in samples], allow_redirects=True
        ):
            size.append(req.content_length / samples[c_].duration)
        size = mean(size) * sum([x.duration for x in seg])
        return int(size)

    @call_log(logger)
    async def download_video(
        self, src_index: int, save_path: Path, update_fn=None
    ):
        with self.set_src(src_index):
            with aria2_temp_dir() as dir_:
                dir_path = Path(dir_)
                async with self.aria2_session.with_download_many(
                    urls=[x for x in self._src.seg],
                    update_fn=update_fn,
                    save_dir=dir_path,
                ) as dl_:
                    async with aiofiles.open(save_path, "wb") as f_w:
                        for d_ in dl_:
                            async with aiofiles.open(
                                dir_path / d_.name, "rb"
                            ) as f_r:
                                await f_w.write(await f_r.read())


class PornEZ(BaseM3U8Downloader):
    _url = None
    _base_content = None
    _base_bs4 = None

    async def prepare__base_content(self):
        self._base_content, self._base_bs4 = await super(
            PornEZ, self
        ).prepare__base_content()
        self._url = self.url
        self.url = self._base_bs4.iframe["src"]
        return await super(PornEZ, self).prepare__base_content()

    async def prepare__source_list(self):
        source_list = []
        for src in self.base_bs4.find_all("source"):
            name_: str = src.attrs["title"]
            url_: HttpUrl = src.attrs["src"]
            src_: M3U8 = await self.get_m3u8_src(url_)
            size_: int = await self.get_size(src_)
            s_ = Source(
                name=name_,
                url=url_,
                size=size_,
                seg=[x.absolute_uri for x in src_.segments],
            )
            source_list.append(s_)
        return source_list

    async def prepare__name(self):
        strip = " Watch porn video in high quality - pornez"
        return self._base_bs4.title.text[: -len(strip)]

    async def prepare__metadata(self):
        metadata = {}
        for i_ in self._base_bs4.find_all("meta"):
            if i_.attrs.get("itemprop", "") == "duration":
                metadata["duration"] = isodate.parse_duration(
                    i_.attrs["content"]
                )
                break
        return metadata

    async def prepare__image_list(self):
        image_urls = []
        data = re.findall(r'sprite:\s"(.+)",', self.base_content.decode())[0]
        image_urls.append(data)
        data = re.findall(r'posterImage:\s"(.+)"', self.base_content.decode())[
            0
        ]
        image_urls.append(data)
        return image_urls


class XVideos(BaseM3U8Downloader):
    async def prepare__source_list(self):
        main_src_url = re.findall(
            r"html5player\.setVideoHLS\('(.+)'\);", self.base_content.decode()
        )[0]
        main_src = await self.get_m3u8_src(main_src_url)
        url_prefix = main_src_url.rsplit("/", 1)[0] + "/"
        source_list = []
        for src__ in main_src.data["playlists"]:
            name_: str = src__["stream_info"]["name"].strip('"')
            url_: HttpUrl = url_prefix + src__["uri"]
            src_: M3U8 = await self.get_m3u8_src(url_, base_url=url_prefix)
            size_: int = await self.get_size(src_)
            s_ = Source(
                name=name_,
                url=url_,
                size=size_,
                seg=[x.absolute_uri for x in src_.segments],
            )
            source_list.append(s_)
        return source_list

    async def prepare__image_list(self):
        image_list = []
        img_url = re.findall(
            r"html5player\.setThumbSlideBig\('(.+)'\);",
            self.base_content.decode(),
        )[0]
        image_list.append(img_url)
        img_url = self.base_bs4.find(
            "meta", attrs={"property": "og:image"}
        ).get("content")
        image_list.append(img_url)
        return image_list

    async def prepare__name(self):
        return self.base_bs4.title.text

    async def prepare__metadata(self):
        metadata = {}
        dur = re.findall(r'"duration":\s"(.+)",', self.base_content.decode())[
            0
        ]
        metadata["duration"] = isodate.parse_duration(dur)
        return metadata


class TubePornClassic(BaseDownloader):
    _base_url = "https://tubepornclassic.com"
    _metadata: dict
    _video_data: dict

    async def prepare__base_content(self):
        return None, None

    async def prepare__source_list(self) -> BaseDownloader.source_list:
        _life_time = 86400
        _video_id = str(self.url).split("/", 5)[4]
        u_ = self._base_url + tpc__detail.detail(_life_time, _video_id)
        async with self.http_session.get(url=u_) as req:
            self._metadata = (await req.json())["video"]
        u_ = f"{self._base_url}/api/videofile.php?video_id={_video_id}&lifetime={_life_time}00"
        h_ = {"referer": self._base_url}
        async with self.http_session.get(url=u_, headers=h_) as req:
            self._video_data = (await req.json())[0]
        s_name = "HQ"
        s_url = self._base_url + tpc__decode.decode(
            self._video_data["video_url"]
        )
        if self._video_data["format"] == ".mp4":
            pass
        else:
            raise NotSupportedFile()
        s_size = await self.get_size(s_url)
        source_list = [Source(name=s_name, url=s_url, size=s_size, seg=[])]
        return source_list

    async def prepare__image_list(self):
        return [self._metadata["thumbsrc"]]

    async def prepare__name(self) -> BaseDownloader.name:
        return self._metadata["title"]

    async def prepare__metadata(self) -> BaseDownloader.metadata:
        metadata = {"duration": self._metadata["duration"]}
        return metadata


DOWNLOADER_MAP = {
    "pornez.net": PornEZ,
    "xvideos.com": XVideos,
    "tubepornclassic.com": TubePornClassic,
}


@call_log(logger)
def get_downloader(url) -> BaseDownloader:
    url = urllib.parse.quote(url, safe="%/:=&?~#+!$,;'@()*[]")
    scheme, netloc, path, qs, anchor = urllib.parse.urlsplit(url)
    if netloc.startswith("www."):
        netloc = netloc[len("www.") :]
    url_parsed = urllib.parse.urlunsplit((scheme, netloc, path, qs, anchor))
    try:
        return DOWNLOADER_MAP[netloc](url_parsed)
    except KeyError:
        raise NotSupportedSite()


def aria2_temp_dir():
    return tempfile.TemporaryDirectory(dir=Settings.DOWNLOADER_ARIA2_DIR)
