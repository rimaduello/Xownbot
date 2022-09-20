import inspect
import re
import sys
from abc import abstractmethod, ABCMeta
from typing import List, Union, Optional, Type

import isodate
from bs4 import BeautifulSoup
from yarl import URL

from Core.logger import call_log, get_logger
from Downloader.exception import NotSupportedFile, NotSupportedSite
from Downloader.helpers import tpc__detail, tpc__decode
from Downloader.http import AioHttpClient
from Downloader.media import GenericMedia, M3U8Media
from utils.helpers import AutoCallMixin
from utils.types import URLOrStr, urlorstr_2_url

logger = get_logger(__name__)


class BaseExtractor(AutoCallMixin, metaclass=ABCMeta):
    def __init__(self, url: Union[str, URL], *args, **kwargs):
        super().__init__(*args, **kwargs)
        if isinstance(url, str):
            url = URL(url)
        self.url = url
        self.title = "untitled"
        self.metadata = {}
        self.src_image: List[GenericMedia] = []
        self.src_video: List[GenericMedia] = []
        self.ready = False

    async def extract(self):
        await self.async_auto_call(prefix="_extract__", assign=True)
        for s_ in self.src_image:
            await s_.make_ready()
        for s_ in self.src_video:
            await s_.make_ready()
        self.ready = True
        return self

    @property
    def src_video__sorted(self):
        return sorted(self.src_video, key=lambda x: x.size)

    # ===========================================================
    @call_log(logger)
    async def _get_content(self, url: Optional[URLOrStr] = None):
        if url is None and {"content__raw", "content__bs"}.issubset(
            self._context.keys()
        ):
            return self._context["content__raw"], self._context["content__bs"]
        url = url or self.url
        async with AioHttpClient().get(url=url) as data_:
            content = await data_.read()
        return content, BeautifulSoup(content, "html.parser")

    @call_log(logger)
    async def _extract__content__10(self):
        content__raw, content__bs = await self._get_content()
        return dict(content__raw=content__raw, content__bs=content__bs)

    @call_log(logger)
    async def _extract__title__20(self):
        # noinspection PyUnresolvedReferences
        return {"title": (await self._get_content())[1].title.text}

    @call_log(logger)
    async def _extract__post_process__100(self):
        return dict(content__raw=None, content__bs=None)

    # ===========================================================
    # noinspection PyPep8Naming
    @property
    @abstractmethod
    def URLS(self) -> List[URL]:
        raise NotImplementedError


class XVideosExtractor(BaseExtractor):
    URLS = ["xvideos.com"]

    @call_log(logger)
    async def _extract__metadata__30(self):
        content__raw, content__bs = await self._get_content()
        metadata = {}
        dur = re.findall(r'"duration":\s"(.+)",', content__raw.decode())[0]
        metadata["duration"] = isodate.parse_duration(dur).__str__()
        return {"metadata": metadata}

    @call_log(logger)
    async def _extract__image_src__40(self):
        content__raw, content__bs = await self._get_content()
        srcs = []
        img_url = re.findall(
            r"html5player\.setThumbSlideBig\('(.+)'\);",
            content__raw.decode(),
        )[0]
        srcs.append(GenericMedia(img_url))
        img_url = content__bs.find("meta", attrs={"property": "og:image"}).get(
            "content"
        )
        srcs.append(GenericMedia(img_url))
        return {"src_image": srcs}

    @call_log(logger)
    async def _extract__video_src__50(self):
        content__raw, content__bs = await self._get_content()
        playlist_url = re.findall(
            r"html5player\.setVideoHLS\('(.+)'\);", content__raw.decode()
        )[0]
        _, srcs = await M3U8Media.parse_playlist(playlist_url)
        return {"src_video": srcs}


class PornEZExtractor(BaseExtractor):
    URLS = ["pornez.net"]

    @call_log(logger)
    async def _extract__content__10(self):
        content_1 = await super(PornEZExtractor, self)._extract__content__10()
        url_2 = content_1["content__bs"].iframe["src"]
        content__raw_2, content__bs_2 = await self._get_content(url_2)
        return {
            **content_1,
            **dict(content__raw_2=content__raw_2, content__bs_2=content__bs_2),
        }

    @call_log(logger)
    async def _extract__title__20(self):
        title_ = await super()._extract__title__20()
        strp = " Watch porn video in high quality - pornez"
        title_["title"] = title_["title"][: -len(strp)]
        return title_

    async def _extract__metadata__30(self):
        metadata = {}
        for i_ in self._context["content__bs"].find_all("meta"):
            if i_.attrs.get("itemprop", "") == "duration":
                metadata["duration"] = isodate.parse_duration(
                    i_.attrs["content"]
                ).__str__()
                break
        return {"metadata": metadata}

    @call_log(logger)
    async def _extract__image_src__40(self):
        srcs = []
        data = re.findall(
            r'sprite:\s"(.+)",', self._context["content__raw_2"].decode()
        )[0]
        srcs.append(GenericMedia(data))
        data = re.findall(
            r'posterImage:\s"(.+)"', self._context["content__raw_2"].decode()
        )[0]
        srcs.append(GenericMedia(data))
        return {"src_image": srcs}

    @call_log(logger)
    async def _extract__video_src__50(self):
        srcs = []
        for src in self._context["content__bs_2"].find_all("source"):
            url_ = src.attrs["src"]
            title_: str = src.attrs["title"]
            srcs.append(M3U8Media(url=url_, title=title_))
        return {"src_video": srcs}

    @call_log(logger)
    async def _extract__post_process__100(self):
        ret = await super()._extract__post_process__100()
        return {**ret, **dict(content__raw_2=None, content__bs_2=None)}


class TubePornClassicExtractor(BaseExtractor):
    URLS = ["tubepornclassic.com"]
    _base_url = "https://tubepornclassic.com"

    @call_log(logger)
    async def _extract__content__10(self):
        context_1 = await super(
            TubePornClassicExtractor, self
        )._extract__content__10()
        _life_time = 86400
        _video_id = str(self.url).split("/", 5)[4]
        u_ = self._base_url + tpc__detail.detail(_life_time, _video_id)
        async with AioHttpClient().get(url=u_) as req:
            _metadata = (await req.json())["video"]
        _video_url = f"{self._base_url}/api/videofile.php?video_id={_video_id}&lifetime={_life_time}00"
        return {
            **context_1,
            **dict(content__metadata=_metadata, video_url=_video_url),
        }

    @call_log(logger)
    async def _extract__title__20(self):
        return {"title": self._context["content__metadata"]["title"]}

    @call_log(logger)
    async def _extract__metadata__30(self):
        metadata = {"duration": self._context["content__metadata"]["duration"]}
        return {"metadata": metadata}

    @call_log(logger)
    async def _extract__image_src__40(self):
        srcs = [GenericMedia(self._context["content__metadata"]["thumbsrc"])]
        return {"src_image": srcs}

    @call_log(logger)
    async def _extract__video_src__50(self):
        h_ = {"referer": self._base_url}
        async with AioHttpClient().get(
            url=self._context["video_url"], headers=h_
        ) as req:
            _video_data = (await req.json())[0]
        s_url = self._base_url + tpc__decode.decode(_video_data["video_url"])
        if _video_data["format"] == ".mp4":
            src_ = GenericMedia(s_url)
        else:
            raise NotSupportedFile()
        srcs = [src_]
        return {"src_video": srcs}


def get_extractor_cls(url: URLOrStr) -> Type[BaseExtractor]:
    url = urlorstr_2_url(url)
    host = url.host
    www_dot = "www."
    if host.startswith(www_dot):
        host = host[len(www_dot) :]
    _extractors = _get_host_extractors()
    for _e in _extractors:
        if host in _e.URLS:
            return _e
    raise NotSupportedSite(url)


def _get_host_extractors():
    _extractors = inspect.getmembers(sys.modules[__name__], inspect.isclass)
    _extractors = [
        x[1]
        for x in _extractors
        if issubclass(x[1], BaseExtractor) and isinstance(x[1].URLS, list)
    ]
    return _extractors


SUPPORTED_SITES = set()
for e_ in _get_host_extractors():
    SUPPORTED_SITES.update(set(e_.URLS))
