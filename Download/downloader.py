import hashlib
import inspect
import os
import pickle
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

from Core.config import Settings
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

    META = [
        "url",
        "name",
        "metadata",
        "base_content",
        "qualities",
        "image_urls",
        "md_hash",
    ]

    def __init__(self, url):
        self.url = url
        self.session = HttpSession()
        self.session_async = AioHttpSession()
        self.name = None
        self.metadata = {}
        self.base_content = None
        self.base_bs4 = None
        self.qualities = []
        self.quality = None
        self.image_urls = []
        self.prepared = False
        self.md_hash = hashlib.md5(url.encode()).hexdigest()

    async def prepare(self):
        logger.info(f"preparing for {self.url}")
        await self.get_base_content()
        await self.get_name()
        await self.get_meta()
        await self.get_qualities()
        await self.get_image_urls()
        logger.info(
            f"preparing for {self.url}: name={self.name} "
            f"size={len(self.base_content)} metadata={self.metadata} "
            f"qualities={self.qualities} images={self.image_urls}"
        )
        self.prepared = True

    async def get_base_content(self):
        data_ = await self.session_async.get_async(url=self.url)
        self.base_content = data_.content
        self.base_bs4 = BeautifulSoup(self.base_content, "html.parser")

    async def download_video(self, writer, update_fn=None):
        log_ = f"{self.url} quality={self.quality['name']} url={self.quality['url']}"
        logger.info(f"video download request: {log_}")
        data_ = await self.session_async.get_async(url=self.quality["url"])
        writer.write(data_.content)
        logger.info(f"video download request done: {log_}")

    async def download_image(self, writer, i):
        log_ = f"{self.url} url={self.image_urls[i]}"
        logger.info(f"image download request: {log_}")
        data_ = await self.session_async.get_async(url=self.image_urls[i])
        writer.write(data_.content)
        logger.info(f"image download request done: {log_}")

    def set_quality(self, q_name: str):
        for q_ in self.qualities:
            if q_["name"] == q_name:
                self.quality = q_
                break

    def save(self):
        meta_ = {}
        file_ = self.save_file_path
        for m_ in self.META:
            meta_[m_] = getattr(self, m_)
        logger.debug(f"dumping self: {meta_}")
        with open(file_, "wb") as f_:
            pickle.dump(meta_, f_)

    def load(self, not_exist_ok=True):
        file_ = self.save_file_path
        if not file_.is_file():
            if not not_exist_ok:
                raise FileNotFoundError
            logger.warning(
                f"file {file_} for url {self.url} with md hash {self.md_hash} not found"
            )
            return
        with open(file_, "rb") as f_:
            meta_ = pickle.load(f_)
        logger.debug(f"loading self: {meta_}")
        for m_ in self.META:
            setattr(self, m_, meta_[m_])
        self.prepared = True

    @property
    def save_file_path(self):
        return Settings.DOWNLOADER_SAVE_PATH / self.md_hash

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
    META = BaseDownloader.META + ["src_list"]

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

    async def download_video(self, writer, update_fn=None):
        log_ = f"{self.url} quality={self.quality['name']} url={self.quality['url']}"
        logger.info(f"video download request: {log_}")
        src_ = self.src_list[self.quality["name"]]
        with tempfile.TemporaryDirectory() as dir_:
            async for c_, d_ in self.session_async.get_many_async(
                urls=[x.absolute_uri for x in src_.segments]
            ):
                with open(os.path.join(dir_, str(c_)), "wb") as f_:
                    f_.write(d_.content)
                    if update_fn:
                        tmp_ = update_fn(total=len(src_.segments), rel=1)
                        if inspect.iscoroutinefunction(update_fn):
                            await tmp_

            for c_, _ in enumerate(src_.segments):
                with open(os.path.join(dir_, str(c_)), "rb") as f_:
                    writer.write(f_.read())
        logger.info(f"video download request done: {log_}")


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
                self.metadata["duration"] = isodate.parse_duration(
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
        self.metadata["duration"] = isodate.parse_duration(dur)

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
    url = urllib.parse.quote(url, safe="%/:=&?~#+!$,;'@()*[]")
    scheme, netloc, path, qs, anchor = urllib.parse.urlsplit(url)
    if netloc.startswith("www."):
        netloc = netloc[len("www.") :]
    url_parsed = urllib.parse.urlunsplit((scheme, netloc, path, qs, anchor))
    return DOWNLOADER_MAP[netloc](url_parsed)
