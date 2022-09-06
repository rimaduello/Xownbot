import asyncio
import logging
from abc import ABC, abstractmethod
from functools import partialmethod
from typing import Callable, Optional

import aiohttp

from Core.config import Settings
from Core.logger import get_logger, call_log

logger = get_logger(__name__)


class BaseClient(ABC):
    @property
    def proxy(self):
        return Settings.HTTP_PROXY

    @abstractmethod
    def get(self, url, *args, **kwargs):
        raise NotImplementedError

    @abstractmethod
    def head(self, url, *args, **kwargs):
        raise NotImplementedError


class AioHttpClient(BaseClient):
    GET_KEY = "get"
    HEAD_KEY = "head"

    def __init__(self):
        super(AioHttpClient, self).__init__()

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
        req = _AsyncRequestCall(
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
        **kwargs,
    ):
        async def _call(counter, **kwargs_):
            return counter, await self._call_async(**kwargs_)()

        session = session or self.session
        tasks = [
            _call(counter=c_, fn=fn, url=x, session=session, **kwargs)
            for c_, x in enumerate(urls)
        ]
        for t_ in asyncio.as_completed(tasks):
            res = await t_
            yield res
        await session.close()

    get: Callable = partialmethod(_call_async, fn=GET_KEY)
    head: Callable = partialmethod(_call_async, fn=HEAD_KEY)
    get_many: Callable = partialmethod(_call_many_async, fn=GET_KEY)
    head_many: Callable = partialmethod(_call_many_async, fn=HEAD_KEY)


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
