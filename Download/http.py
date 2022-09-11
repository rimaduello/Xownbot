import asyncio
import inspect
from asyncio import sleep
from contextlib import asynccontextmanager
from functools import partialmethod, cached_property
from pathlib import Path
from typing import Callable, Optional, List, Union, AsyncIterator

import aiohttp
import aria2p

from Core.config import Settings
from Core.logger import get_logger, call_log
from Download.exception import DownloadError

logger = get_logger(__name__)


class AioHttpClient:
    GET_KEY = "get"
    HEAD_KEY = "head"
    proxy = Settings.HTTP_PROXY

    class _AsyncRequestCall:
        def __init__(self, session, function, *args, **kwargs):
            self.session = session
            self.function = function
            self.call_args = args
            self.call_kwargs = kwargs

        @call_log(logger)
        async def __aenter__(self):
            self.req_obj = await self()
            return self.req_obj

        @call_log(logger)
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            self.req_obj.release()
            await self.session.close()

        @call_log(logger)
        async def __call__(self):
            resp = await self.function(*self.call_args, **self.call_kwargs)
            return resp

    @property
    def session(self):
        connector = aiohttp.TCPConnector(
            limit_per_host=Settings.DOWNLOADER_THROTTLING
        )
        return aiohttp.ClientSession(connector=connector)

    def _get_call_fn(self, session, fn):
        _call_map = {
            self.GET_KEY: session.get,
            self.HEAD_KEY: session.head,
        }
        cl_ = _call_map[fn]
        return cl_

    @call_log(logger)
    def _call_async(
        self,
        fn,
        *_,
        url,
        session: Optional[aiohttp.ClientSession] = None,
        **kwargs,
    ):
        session = session or self.session
        fn = self._get_call_fn(session, fn)
        req = self._AsyncRequestCall(
            session, fn, url=url, proxy=self.proxy, **kwargs
        )
        return req

    @call_log(logger)
    async def _call_many_async(
        self,
        fn,
        *_,
        urls: list,
        session: Optional[aiohttp.ClientSession] = None,
        headers: Union[dict, List[dict]] = None,
        **kwargs,
    ):
        async def _call(counter, **kwargs_):
            return counter, await self._call_async(**kwargs_)()

        headers = headers or kwargs.pop("headers", None)
        session = session or self.session
        if headers:
            if isinstance(headers, dict):
                headers = [headers] * len(urls)
        else:
            headers = [None] * len(urls)
        tasks = [
            _call(
                counter=c_,
                fn=fn,
                url=u_,
                session=session,
                headers=h_,
                **kwargs,
            )
            for c_, (u_, h_) in enumerate(zip(urls, headers))
        ]
        for t_ in asyncio.as_completed(tasks):
            res = await t_
            yield res
        await session.close()

    get: Callable = partialmethod(_call_async, fn=GET_KEY)
    head: Callable = partialmethod(_call_async, fn=HEAD_KEY)
    get_many: Callable = partialmethod(_call_many_async, fn=GET_KEY)
    head_many: Callable = partialmethod(_call_many_async, fn=HEAD_KEY)


class Aria2Client:
    aria2_uri = Settings.DOWNLOADER_ARIA2_URL
    aria2_url = aria2_uri.scheme + "://" + aria2_uri.host
    aria2_port = aria2_uri.port
    aria2_token = Settings.DOWNLOADER_ARIA2_TOKEN

    def __init__(self):
        self.aria2_download_path = Path(self.session.get_global_options().dir)

    @cached_property
    def session(self):
        return aria2p.API(
            aria2p.Client(
                self.aria2_url,
                port=self.aria2_port,
                secret=self.aria2_token,
            )
        )

    async def download_many(
        self,
        urls: List[str],
        update_fn=None,
        save_dir: Path = None,
        cb_use_length=False,
        **kwargs,
    ):
        save_dir = (
            self.path2aria(save_dir) if save_dir else self.aria2_download_path
        )
        kwargs["dir"] = str(save_dir)
        download_list = self._add_downloads(urls, **kwargs)
        cb_fn = self._callback_factory(update_fn, use_length=cb_use_length)
        return await self._await_complete(download_list, update_fn=cb_fn)

    async def download(
        self,
        url: str,
        update_fn=None,
        save_dir: Path = None,
        cb_use_length=True,
        **kwargs,
    ):
        return await self.download_many(
            urls=[url],
            update_fn=update_fn,
            save_dir=save_dir,
            cb_use_length=cb_use_length,
            **kwargs,
        )

    @asynccontextmanager
    async def with_download_many(
        self,
        urls: List[str],
        update_fn=None,
        save_dir=None,
        cb_use_length=False,
        **kwargs,
    ) -> List[aria2p.Download]:
        downloads = await self.download_many(
            urls=urls,
            update_fn=update_fn,
            save_dir=save_dir,
            cb_use_length=cb_use_length,
            **kwargs,
        )
        try:
            yield downloads
        finally:
            self.session.remove(downloads, True, True, True)

    @asynccontextmanager
    async def with_download(
        self,
        url: str,
        update_fn=None,
        save_dir=None,
        cb_use_length=True,
        **kwargs,
    ) -> AsyncIterator[aria2p.Download]:
        downloads = await self.download(
            url=url,
            update_fn=update_fn,
            save_dir=save_dir,
            cb_use_length=cb_use_length,
            **kwargs,
        )
        try:
            yield downloads[0]
        finally:
            self.session.remove(downloads, True, True, True)

    def path2aria(self, path: Path):
        if Settings.DOWNLOADER_ARIA2_DIR in path.parents:
            path = path.relative_to(Settings.DOWNLOADER_ARIA2_DIR)
        return self.aria2_download_path / path

    def _add_downloads(self, urls: List[str], **kwargs):
        download_list = []
        for u_ in urls:
            d_ = self._download(u_, **kwargs)
            download_list.append(d_.gid)
        return download_list

    async def _await_complete(self, gids: List[str], update_fn=None):
        while True:
            stat = self.session.get_downloads(gids)
            is_complete = True
            for s_ in stat:
                if s_.error_code and s_.error_code != "0":
                    raise DownloadError(s_.error_code, s_.error_message)
                is_complete &= s_.is_complete
            if is_complete:
                break
            if update_fn:
                tmp_ = update_fn(stat)
                if inspect.iscoroutinefunction(update_fn):
                    await tmp_
            await sleep(1)
        return stat

    def _download(self, url: str, **kwargs):
        url = [url]
        return self.session.add_uris(uris=url, options=kwargs)

    @staticmethod
    def _callback_factory(fn, use_length=False):
        async def _fn(downloads: List[aria2p.Download]):
            total = (
                sum([x.total_length for x in downloads])
                if use_length
                else len(downloads)
            )
            completed = 0
            for d_ in downloads:
                if use_length:
                    completed += d_.completed_length
                else:
                    completed += 1 if d_.is_complete else 0
            tmp_ = fn(total, completed)
            if inspect.iscoroutinefunction(fn):
                await tmp_

        if fn:
            return _fn
        else:
            return None
