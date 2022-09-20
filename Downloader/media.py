import random
import tempfile
from abc import abstractmethod, ABCMeta
from pathlib import Path
from statistics import mean
from typing import Optional

import aiofiles
import m3u8
from m3u8 import SegmentList

from Core.config import Settings
from Core.logger import call_log, get_logger
from Downloader.http import AioHttpClient, Aria2Client
from utils.helpers import async_move_file, AutoCallMixin, size_hr
from utils.types import URLOrStr, urlorstr_2_url, PathOrStr, pathorstr_2_path

logger = get_logger(__name__)


class BaseMedia(AutoCallMixin, metaclass=ABCMeta):
    def __init__(self, url: URLOrStr, title: str = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        url = urlorstr_2_url(url)
        self.url = url
        self.title = title or "media"
        self.extension: str = ""
        self.size: int = -1
        self.ready = False
        self._context = {}

    async def make_ready(self):
        await self.async_auto_call(prefix="_make_ready__", assign=True)
        self.ready = True
        return self

    async def download(self, save_path: PathOrStr, update_fn=None):
        if self.DOWNLOAD_DEPENDS_ON_READY and not self.ready:
            await self.make_ready()
        save_path = pathorstr_2_path(save_path)
        with tempfile.TemporaryDirectory(
            dir=Settings.DOWNLOADER_ARIA2_DIR
        ) as dir_:
            download_dir = Path(dir_)
            await self._download(
                save_path=save_path,
                download_dir=download_dir,
                update_fn=update_fn,
            )
            for f_ in download_dir.iterdir():
                if f_.is_file():
                    f_.unlink()

    def __repr__(self):
        _not_ready = "NotReady"
        _repr = [
            f"url: {self.url}",
            f"title: {self.title}",
            f"size: {size_hr(self.size) if self.ready else _not_ready}",
        ]
        return "\n".join(_repr)

    def __str__(self):
        return f"{self.title} ({size_hr(self.size)})"

    # ===========================================================
    @abstractmethod
    async def _download(
        self, save_path: Path, download_dir: PathOrStr, update_fn=None
    ):
        raise NotImplementedError

    # noinspection PyPep8Naming
    @property
    @abstractmethod
    def DOWNLOAD_DEPENDS_ON_READY(self) -> bool:
        raise NotImplementedError


class GenericMedia(BaseMedia):
    DOWNLOAD_DEPENDS_ON_READY = False

    # ===========================================================
    @call_log(logger)
    async def _make_ready__head__5(self) -> dict:
        head_ = await self._get_head()
        return {"head": head_}

    @call_log(logger)
    async def _make_ready__size__10(self) -> dict:
        size_ = (await self._get_head()).content_length
        return {"size": size_}

    @call_log(logger)
    async def _make_ready__extension__20(self) -> dict:
        head_ = await self._get_head()
        return {
            "extension": f".{head_.headers['Content-Type'].split('/')[-1]}"
        }

    @call_log(logger)
    async def _make_ready__postprocess__100(self) -> dict:
        return {"head": None}

    async def _download(
        self, save_path: Path, download_dir: PathOrStr, update_fn=None
    ):
        async with Aria2Client().with_download(
            url=self.url.__str__(),
            update_fn=update_fn,
            save_dir=download_dir,
        ) as dl_:
            name = await Aria2Client().status((dl_,), ["files"])
            name = name[0]["files"][0]["path"]
            name = Path(name).name
            if save_path.is_dir():
                save_path /= name
            await async_move_file(download_dir / name, save_path)

    # ===========================================================
    async def _get_head(self, url: Optional[URLOrStr] = None):
        if "head" in self._context.keys() and url is None:
            return self._context["head"]
        url = url or self.url
        async with AioHttpClient().head(
            url=url, allow_redirects=True
        ) as head_data:
            return head_data


class M3U8Media(BaseMedia):
    DOWNLOAD_DEPENDS_ON_READY = True
    SIZE_ESTIMATE_SAMPLE = 10

    def __init__(self, url: URLOrStr, title: str = None):
        super(M3U8Media, self).__init__(url=url, title=title)
        self.src_list: Optional[SegmentList] = None
        self.extension = ".mp4"

    @classmethod
    async def parse_playlist(cls, url: URLOrStr):
        url = urlorstr_2_url(url)
        m3u8_data = await cls._get_m3u8_cls(url=url)
        srcs = []
        for l_ in m3u8_data.playlists:
            srcs.append(
                cls(
                    url=l_.absolute_uri,
                    title=f"{l_.stream_info.resolution[1]}p",
                )
            )
        return m3u8_data, srcs

    # ===========================================================
    @call_log(logger)
    async def _make_ready__src_list__5(self) -> dict:
        m3u8_data = await self._get_m3u8()
        return {"src_list": m3u8_data.segments}

    @call_log(logger)
    async def _make_ready__size__10(self) -> dict:
        src_list = self._context["src_list"]
        samples = (
            random.sample(src_list, self.SIZE_ESTIMATE_SAMPLE)
            if len(src_list) > self.SIZE_ESTIMATE_SAMPLE
            else src_list
        )
        size = []
        cl_ = AioHttpClient()
        async for c_, req in cl_.head_many(
            urls=[x.absolute_uri for x in samples], allow_redirects=True
        ):
            size.append(req.content_length / samples[c_].duration)
        size = mean(size) * sum([x.duration for x in src_list])
        return {"size": int(size)}

    async def _download(
        self, save_path: Path, download_dir: PathOrStr, update_fn=None
    ):
        async with Aria2Client().with_download_many(
            urls=[x.absolute_uri for x in self.src_list],
            update_fn=update_fn,
            save_dir=download_dir,
        ) as dl_:
            dl_files = await Aria2Client().status(dl_, ["files"])
            dl_files = [Path(x["files"][0]["path"]).name for x in dl_files]
            async with aiofiles.open(save_path, "wb") as f_w:
                for d_ in dl_files:
                    async with aiofiles.open(download_dir / d_, "rb") as f_r:
                        await f_w.write(await f_r.read())

    # ===========================================================
    @classmethod
    async def _get_m3u8_cls(cls, url):
        async with AioHttpClient().get(url=url) as data_:
            src_raw = await data_.text()
        return m3u8.loads(src_raw, uri=url.__str__())

    async def _get_m3u8(self, url: Optional[URLOrStr] = None):
        url = url or self.url
        return await self._get_m3u8_cls(url)
