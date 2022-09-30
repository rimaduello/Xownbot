import random
import tempfile
import time
from abc import abstractmethod, ABCMeta
from pathlib import Path
from statistics import mean
from typing import List, Union, Dict, ClassVar
from uuid import uuid4

import aiofiles
import m3u8
from pydantic import BaseModel, AnyHttpUrl, PrivateAttr, Field
from yarl import URL

from Core.config import Settings
from Core.logger import get_logger
from Downloader.http import Aria2Client, AioHttpClient
from utils.helpers import size_hr, async_move_file
from utils.types import PathOrStr, pathorstr_2_path
import dill

logger = get_logger(__name__)


class BaseMedia(BaseModel, metaclass=ABCMeta):
    url: Union[AnyHttpUrl, URL]
    title: str = "media"
    extension: str = ""
    size: int = -1
    _ready = PrivateAttr(False)

    # ===========================================================
    async def download(self, save_path: PathOrStr, update_fn=None):
        if not self._ready:
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

    async def make_ready(self):
        self._ready = True

    @property
    def size_hr(self) -> str:
        return size_hr(self.size) if self.size else "unknown size"

    # ===========================================================
    class Config:
        arbitrary_types_allowed = True

    def __repr__(self):
        _repr = [
            f"url: {self.url}",
            f"title: {self.title}",
            f"ready: {self._ready}",
            f"size: {self.size_hr}",
        ]
        return "\n".join(_repr)

    def __str__(self):
        return f"{self.title}{self.extension} ({self.size_hr})"

    # ===========================================================
    @abstractmethod
    async def _download(
        self, save_path: Path, download_dir: PathOrStr, update_fn=None
    ):
        raise NotImplementedError


class GenericMedia(BaseMedia):
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

    async def make_ready(self):
        if self.size < 0:
            async with AioHttpClient().head(
                url=self.url, allow_redirects=True
            ) as req_:
                self.size = req_.content_length
        return await super().make_ready()


class M3U8Media(BaseMedia):
    SIZE_ESTIMATE_SAMPLE: ClassVar = 10
    extension = ".ts"
    _m3u8_data = PrivateAttr()

    async def make_ready(self):
        self._m3u8_data = (await self._get_m3u8_cls()).segments
        if self.size < 0:
            self.size = await self._get_m3u8_size()
        return await super().make_ready()

    # ===========================================================
    async def _get_m3u8_cls(self):
        async with AioHttpClient().get(url=self.url) as data_:
            src_raw = await data_.text()
        return m3u8.loads(src_raw, uri=self.url.__str__())

    async def _get_m3u8_size(self):
        src_list = self._m3u8_data
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
        return int(size)

    async def _download(
        self, save_path: Path, download_dir: PathOrStr, update_fn=None
    ):
        async with Aria2Client().with_download_many(
            urls=[x.absolute_uri for x in self._m3u8_data],
            update_fn=update_fn,
            save_dir=download_dir,
        ) as dl_:
            dl_files = await Aria2Client().status(dl_, ["files"])
            dl_files = [Path(x["files"][0]["path"]).name for x in dl_files]
            async with aiofiles.open(save_path, "wb") as f_w:
                for d_ in dl_files:
                    async with aiofiles.open(download_dir / d_, "rb") as f_r:
                        await f_w.write(await f_r.read())


class BAClientResult(BaseModel):
    timestamp: float = Field(default_factory=time.time, const=True)
    hash: str = Field(default_factory=lambda: uuid4().hex, const=True)
    title: str
    metadata: Dict = {}
    image: List[GenericMedia] = []
    video: List[GenericMedia] = []

    def save(self):
        with (Settings.DOWNLOADER_SAVE_PATH / self.hash).open("wb") as f_:
            dill.dump(self, f_)

    @classmethod
    def load(cls, hash_str: str):
        with (Settings.DOWNLOADER_SAVE_PATH / hash_str).open("rb") as f_:
            return dill.load(f_)
