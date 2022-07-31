import os
import random
import re
import tempfile
import urllib.parse
from abc import ABC, abstractmethod
from statistics import mean
from typing import TypedDict, List, Dict, Optional

import isodate
import m3u8
from bs4 import BeautifulSoup
from m3u8 import M3U8

from Core.logger import get_logger
from Download.http import HttpSession, AioHttpSession

logger = get_logger("DOWNLOADER")


class Quality(TypedDict):
    name: str
    url: str
    size: int


class BaseDownloader(ABC):
    quality: Optional[Quality]
    qualities: List[Quality]
    image_urls: List

    def __init__(self, url):
        self.url = url
        self.session = HttpSession()
        self.session_async = AioHttpSession()
        self.name = None
        self.meta = {}
        self.base_content = None
        self.base_bs4 = None
        self.qualities = []
        self.quality = None
        self.image_urls = []

    async def prepare(self):
        logger.info(f"preparing for {self.url}")
        await self.get_base_content()
        logger.info(f"got content with size {len(self.base_content)}")
        logger.debug(f"got content {self.base_content}")
        await self.get_name()
        logger.info(f"determined name {self.name}")
        await self.get_meta()
        logger.info(f"determined meta {self.meta}")
        await self.get_qualities()
        logger.info(f"available qualities {self.qualities}")
        await self.get_image_urls()
        logger.info(f"available images {self.image_urls}")

    async def get_base_content(self):
        data_ = await self.session_async.get_async(url=self.url)
        self.base_content = data_.content
        self.base_bs4 = BeautifulSoup(self.base_content, "html.parser")

    async def download_video(self, writer):
        data_ = await self.session_async.get_async(url=self.quality["url"])
        writer.write(data_.content)

    async def download_image(self, writer, i):
        data_ = await self.session_async.get_async(url=self.image_urls[i])
        writer.write(data_.content)

    def set_quality(self, q_name: str):
        for q_ in self.qualities:
            if q_["name"] == q_name:
                self.quality = q_
                break

    @abstractmethod
    async def get_name(self):
        pass

    @abstractmethod
    async def get_meta(self):
        pass

    @abstractmethod
    async def get_qualities(self):
        pass

    @abstractmethod
    async def get_image_urls(self):
        pass

    @property
    @abstractmethod
    def file_name(self):
        pass


class BaseM3U8BaseDownloader(BaseDownloader, ABC):
    src_list: Dict[str, M3U8]
    size_estimate_sample = 10

    def __init__(self, *args, **kwargs):
        super(BaseM3U8BaseDownloader, self).__init__(*args, **kwargs)
        self.src_list = {}

    async def get_src(self, url, base_url=None):
        data_ = await self.session_async.get_async(url=url)
        src_raw = data_.content.decode()
        return m3u8.loads(src_raw, base_url)

    async def get_size(self, src: M3U8):
        seg = src.segments
        samples = (
            random.sample(seg, self.size_estimate_sample)
            if len(seg) > self.size_estimate_sample
            else seg
        )
        size = []
        async for c_, req in self.session_async.head_many_async(
            urls=[x.absolute_uri for x in samples], allow_redirects=True
        ):
            size.append(req.content_length / samples[c_].duration)
        size = mean(size) * sum([x.duration for x in seg])
        return int(size)

    async def download_video(self, writer):
        src_ = self.src_list[self.quality["name"]]
        with tempfile.TemporaryDirectory() as dir_:
            async for c_, d_ in self.session_async.get_many_async(
                urls=[x.absolute_uri for x in src_.segments]
            ):
                with open(os.path.join(dir_, str(c_)), "wb") as f_:
                    f_.write(d_.content)
            for c_, _ in enumerate(src_.segments):
                with open(os.path.join(dir_, str(c_)), "rb") as f_:
                    writer.write(f_.read())


class PornEZ(BaseM3U8BaseDownloader):
    _url = None
    _base_content = None
    _base_bs4 = None

    async def get_base_content(self):
        await super(PornEZ, self).get_base_content()
        self._url = self.url
        self._base_content = self.base_content
        self._base_bs4 = self.base_bs4
        self.url = self.base_bs4.iframe["src"]
        await super(PornEZ, self).get_base_content()

    async def get_name(self):
        lstrip = " Watch porn video in high quality - pornez"
        self.name = self._base_bs4.title.text[: -len(lstrip)] + ".mp4"

    async def get_meta(self):
        for i_ in self._base_bs4.find_all("meta"):
            if i_.attrs.get("itemprop", "") == "duration":
                self.meta["duration"] = isodate.parse_duration(
                    i_.attrs["content"]
                )
                break

    async def get_qualities(self):
        for src in self.base_bs4.find_all("source"):
            name_ = src.attrs["title"]
            url_ = src.attrs["src"]
            src_ = await self.get_src(url_)
            size_ = await self.get_size(src_)
            self.qualities.append({"name": name_, "url": url_, "size": size_})
            self.src_list[name_] = src_

    async def get_image_urls(self):
        data = re.findall(r'sprite:\s"(.+)",', self.base_content.decode())[0]
        self.image_urls.append(data)
        data = re.findall(r'posterImage:\s"(.+)"', self.base_content.decode())[
            0
        ]
        self.image_urls.append(data)

    @property
    def file_name(self):
        name = ("pornez_" + self.name.replace(" ", "-")).rsplit(".", 1)
        name.insert(1, self.quality["name"])
        return ".".join(name)


class XVideos(BaseM3U8BaseDownloader):
    async def get_name(self):
        self.name = self.base_bs4.title.text + ".mp4"

    async def get_meta(self):
        dur = re.findall(r'"duration":\s"(.+)",', self.base_content.decode())[
            0
        ]
        self.meta["duration"] = isodate.parse_duration(dur)

    async def get_qualities(self):
        main_src_url = re.findall(
            r"html5player\.setVideoHLS\('(.+)'\);", self.base_content.decode()
        )[0]
        main_src = await self.get_src(main_src_url)
        url_prefix = main_src_url.rsplit("/", 1)[0] + "/"
        for src__ in main_src.data["playlists"]:
            name_ = src__["stream_info"]["name"].strip('"')
            url_ = url_prefix + src__["uri"]
            src_ = await self.get_src(url_, base_url=url_prefix)
            size_ = await self.get_size(src_)
            self.qualities.append({"name": name_, "url": url_, "size": size_})
            self.src_list[name_] = src_

    async def get_image_urls(self):
        img_url = re.findall(
            r"html5player\.setThumbSlideBig\('(.+)'\);",
            self.base_content.decode(),
        )[0]
        self.image_urls.append(img_url)

    @property
    def file_name(self):
        name = self.name.rsplit(".", 1)
        name.insert(1, self.quality["name"])
        return ".".join(name)


DOWNLOADER_MAP = {"pornez.net": PornEZ, "xvideos.com": XVideos}


def get_downloader(url) -> BaseDownloader:
    scheme, netloc, path, qs, anchor = urllib.parse.urlsplit(url)
    if netloc.startswith("www."):
        netloc = netloc[len("www.") :]
    path = urllib.parse.quote(path, "/%")
    url_parsed = urllib.parse.urlunsplit((scheme, netloc, path, None, None))
    return DOWNLOADER_MAP[netloc](url_parsed)
