import asyncio
import inspect
from asyncio import sleep, gather
from contextlib import asynccontextmanager
from functools import partialmethod, cached_property
from pathlib import Path
from typing import (
    Callable,
    Optional,
    List,
    Union,
    AsyncGenerator,
    Tuple,
    TypeVar,
    AsyncIterator,
)

import aioaria2
import aiohttp
from aiohttp import ClientResponse

from Core.config import Settings
from Core.logger import get_logger, call_log
from Downloader.exception import DownloaderError

logger = get_logger(__name__)

AriaGID = TypeVar("AriaGID", bound=str)


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

    get: Callable[..., ClientResponse] = partialmethod(_call_async, fn=GET_KEY)
    head: Callable[..., ClientResponse] = partialmethod(
        _call_async, fn=HEAD_KEY
    )
    get_many: Callable[
        ..., AsyncGenerator[ClientResponse, None]
    ] = partialmethod(_call_many_async, fn=GET_KEY)
    head_many: Callable[
        ..., AsyncGenerator[ClientResponse, None]
    ] = partialmethod(_call_many_async, fn=HEAD_KEY)


class Aria2Client:
    aria2_uri = Settings.DOWNLOADER_ARIA2_URL
    aria2_token = Settings.DOWNLOADER_ARIA2_TOKEN

    @asynccontextmanager
    async def session(self):
        sess_ = aioaria2.Aria2HttpClient(
            self.aria2_uri, token=self.aria2_token
        )
        try:
            yield sess_
        finally:
            await sess_.close()

    @cached_property
    def aria2_download_path(self):
        async def _fn():
            async with self.session() as sess_:
                return (await sess_.getGlobalOption())["dir"]

        result = asyncio.get_event_loop().run_until_complete(_fn())
        return result

    # ===========================================================
    async def download_many(
        self, urls: List[str], save_dir: Path = None, **kwargs
    ):
        save_dir = (
            self.path2aria(save_dir) if save_dir else self.aria2_download_path
        )
        kwargs["dir"] = str(save_dir)
        download_list = await self._add_downloads(urls, **kwargs)
        return download_list

    async def download(self, url: str, save_dir: Path = None, **kwargs):
        return (
            await self.download_many(urls=[url], save_dir=save_dir, **kwargs)
        )[0]

    @asynccontextmanager
    async def with_download_many(
        self,
        urls: List[str],
        update_fn=None,
        save_dir=None,
        cb_use_length=False,
        **kwargs,
    ) -> AsyncIterator[List[AriaGID]]:
        download_list = await self.download_many(
            urls=urls, save_dir=save_dir, **kwargs
        )
        cb_fn = self.callback_factory(update_fn, use_length=cb_use_length)
        try:
            await self.await_complete(download_list, update_fn=cb_fn)
            yield download_list
        finally:
            async with self.session() as sess_:
                tasks = [sess_.forceRemove(u_) for u_ in download_list]
                await asyncio.gather(*tasks, return_exceptions=True)

    @asynccontextmanager
    async def with_download(
        self,
        url: str,
        update_fn=None,
        save_dir=None,
        cb_use_length=True,
        **kwargs,
    ) -> AsyncIterator[AriaGID]:
        async with self.with_download_many(
            urls=[url],
            update_fn=update_fn,
            save_dir=save_dir,
            cb_use_length=cb_use_length,
            **kwargs,
        ) as dl_:
            yield dl_[0]

    async def await_complete(self, gids: Tuple[AriaGID], update_fn=None):
        while True:
            stat = await self.status(gids, ["status"])
            is_complete = True
            for c_, s_ in enumerate(stat):
                if s_["status"] == "error":
                    err_ = (
                        await self.status(
                            (gids[c_],), ["errorCode", "errorMessage"]
                        )
                    )[0]
                    raise DownloaderError(
                        err_["errorCode"], err_["errorMessage"]
                    )
                is_complete &= s_["status"] == "complete"
            if is_complete:
                break
            if update_fn:
                tmp_ = update_fn(gids)
                if inspect.iscoroutinefunction(update_fn):
                    await tmp_
            await sleep(1)

    async def status(self, gids: Tuple[AriaGID], keys=None):
        async with self.session() as sess_:
            tasks = [sess_.tellStatus(x, keys) for x in gids]
            # noinspection PyTypeChecker
            result = await asyncio.gather(*tasks)
        result: List[dict]
        return result

    def path2aria(self, path: Path):
        if Settings.DOWNLOADER_ARIA2_DIR in path.parents:
            path = path.relative_to(Settings.DOWNLOADER_ARIA2_DIR)
        return self.aria2_download_path / path

    def callback_factory(self, fn, use_length=False):
        async def _fn(gids: Tuple[AriaGID]):
            statuses = await self.status(
                gids, ["totalLength", "completedLength", "status"]
            )
            if use_length:
                total = sum([float(x["totalLength"]) for x in statuses])
                completed = sum(
                    [float(x["completedLength"]) for x in statuses]
                )
            else:
                total = len(gids)
                completed = sum([x["status"] == "complete" for x in statuses])
            tmp_ = fn(total, completed)
            if inspect.iscoroutinefunction(fn):
                await tmp_

        if fn:
            return _fn
        else:
            return None

    # ===========================================================
    async def _add_downloads(
        self, urls: List[str], **kwargs
    ) -> Tuple[AriaGID]:
        async with self.session() as sess_:
            tasks_ = [self._download(u_, sess_, **kwargs) for u_ in urls]
            # noinspection PyTypeChecker
            result = await gather(*tasks_, return_exceptions=False)
        result: Tuple[AriaGID]
        return result

    @staticmethod
    async def _download(
        url: str, sess: aioaria2.Aria2HttpClient, **kwargs
    ) -> AriaGID:
        url = [url]
        return await sess.addUri(uris=url, options=kwargs)
