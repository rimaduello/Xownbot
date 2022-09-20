# todo: cache ttl
import hashlib
import pickle
from typing import List, Optional

from Core.config import Settings
from Core.logger import get_logger
from Downloader.extractor import get_extractor_cls
from Downloader.media import GenericMedia
from utils.types import URLOrStr, urlorstr_2_url, PathOrStr, pathorstr_2_path

logger = get_logger(__name__)


class Downloader:
    def __init__(self, url: URLOrStr):
        self.url = urlorstr_2_url(url)
        self.md_hash = hashlib.md5(url.__str__().encode()).hexdigest()
        self.title: str = ""
        self.metadata = {}
        self.src_image: List[GenericMedia] = []
        self.src_video: List[GenericMedia] = []
        self.ready = False
        self._logger = logger.getChild(self.md_hash)

    async def make_ready(self, use_cache=True):
        if use_cache and self.cache_path.is_file():
            self._logger.debug("using cache")
            self.load()
        else:
            _extractor = get_extractor_cls(self.url)(self.url)
            await _extractor.extract()
            self.title = _extractor.title
            self.metadata = _extractor.metadata
            self.src_image = _extractor.src_image
            self.src_video = _extractor.src_video__sorted
            if use_cache:
                self._logger.debug("saving cache")
                self.save()
        self.ready = True

    def save(self, loc: Optional[PathOrStr] = None):
        loc = loc or self.cache_path
        loc = pathorstr_2_path(loc)
        meta_ = {x: getattr(self, x) for x in self._CACHE_ATTRS}
        with loc.open("wb") as f_:
            pickle.dump(meta_, f_)

    def load(self, loc: Optional[PathOrStr] = None):
        loc = loc or self.cache_path
        loc = pathorstr_2_path(loc)
        with loc.open("rb") as f_:
            data = pickle.load(f_)
        for k_, v_ in data.items():
            setattr(self, k_, v_)

    @classmethod
    def load_from_file(cls, md_hash: str, loc: PathOrStr = None):
        loc = loc or Settings.DOWNLOADER_SAVE_PATH
        loc = pathorstr_2_path(loc)
        obj = cls(url="_")
        obj.load(loc / md_hash)
        obj.ready = True
        return obj

    def __repr__(self):
        _not_ready = "NotReady"
        _repr = [
            f"url: {self.url}",
            f"title: {self.title if self.ready else _not_ready}",
            f"metadata: {self.metadata if self.ready else _not_ready}",
        ]
        _repr += ["images:"]
        _repr += (
            [
                f"\t{x.__repr__()}\n{'-' * 10}".replace("\n", "\n\t")
                for x in self.src_image
            ]
            if self.ready
            else [_not_ready]
        )
        _repr += ["videos:"]
        _repr += (
            [
                f"\t{x.__repr__()}\n{'-' * 10}".replace("\n", "\n\t")
                for x in self.src_video
            ]
            if self.ready
            else [_not_ready]
        )

        return "\n".join(_repr)

    @property
    def cache_path(self):
        return Settings.DOWNLOADER_SAVE_PATH / self.md_hash

    _CACHE_ATTRS = [
        "url",
        "md_hash",
        "title",
        "metadata",
        "src_image",
        "src_video",
    ]
