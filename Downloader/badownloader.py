import json
import random
import re
from urllib.parse import quote

import js2py
from async_lru import alru_cache
from yarl import URL

from Core.logger import get_logger, call_log
from Downloader.exception import BAInfoError
from Downloader.http import AioHttpClient
from Downloader.types import BAClientResult, GenericMedia, M3U8Media
from utils.helpers import Singleton, stripe_www
from utils.types import URLOrStr, urlorstr_2_url

logger = get_logger(__name__)


class BAClient(metaclass=Singleton):
    base_url = URL("https://badassdownloader.com/")
    m_url = URL("https://m.badassdownloader.com")
    _ba_data = None

    @alru_cache()
    async def get_ba_data(self):
        if self._ba_data:
            pass
        else:
            async with AioHttpClient().get(
                url=self.m_url / "js" / "bsw.js"
            ) as req_:
                content = await req_.read()
            content = content.decode()
            content = re.sub(r"bspage\.getServer(.|\n)+?};", "", content)
            content = content.replace(
                "}(window.bspage = window.bspage || {}))", "return bspage;}"
            )
            content = content.replace(
                "(function(bspage) {", "function x(bspage) {"
            )
            d_ = js2py.eval_js(content)({})
            self._ba_data = d_
        return self._ba_data

    @call_log(logger)
    async def get_srcs(self, url: URLOrStr) -> BAClientResult:
        url = urlorstr_2_url(url)
        d_u_ = quote(url.__str__(), safe="~()*!'")
        d_d_ = stripe_www(url.host)
        d_ = "info=" + json.dumps({"url": d_u_, "domain": d_d_}).replace(
            " ", ""
        )
        s_ = await self.servers
        s_ = URL(random.choice(s_))
        h_ = {
            "user-agent": "curl/7.68.0",
            "content-type": "application/x-www-form-urlencoded",
        }
        async with AioHttpClient().post(
            url=s_ / "get-info", data=d_, headers=h_
        ) as req_:
            info = await req_.json()
        if not info["success"]:
            raise BAInfoError(url, info["message"])
        title = info["title"]
        image = []
        video = []
        _thmb = info["thumbnail"]
        if _thmb:
            image += [
                GenericMedia(
                    url=self.m_url / "get-image" % {"image": _thmb},
                    title="thumbnail",
                    extension=".jpeg",
                )
            ]
        for q_, src_ in info["sources"]["mp4"].items():
            video += [
                GenericMedia(
                    url=s_ / "download" % {"data": src_["src"]},
                    title=f"{q_}",
                    extension=".mp4",
                    size=src_["size"],
                )
            ]

        for q_, src_ in info["sources"]["m3u8"].items():
            video += [
                GenericMedia(
                    url=s_ / "download" % {"data": src_["src"]},
                    title=f"{q_}",
                    extension=".mpg",
                    size=src_["size"],
                )
            ]
        [await x.make_ready() for x in image]
        [await x.make_ready() for x in video]
        return BAClientResult(title=title, image=image, video=video)

    @property
    async def sites_list(self):
        return (await self.get_ba_data())["sitesList"]

    @property
    async def sites_down(self):
        return (await self.get_ba_data())["sitesDown"]

    @property
    async def sites_multiple(self):
        return (await self.get_ba_data())["sitesMultiple"]

    @property
    async def servers(self):
        return (await self.get_ba_data())["servers"]
