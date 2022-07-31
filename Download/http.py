import asyncio
from abc import ABC, abstractmethod
from functools import partialmethod
from typing import Callable

import aiohttp
import requests

from Core.config import Settings


class BaseSession(ABC):
    @property
    def proxy(self):
        return Settings.HTTP_PROXY

    @abstractmethod
    def get(self, url, *args, **kwargs):
        raise NotImplementedError

    @abstractmethod
    def head(self, url, *args, **kwargs):
        raise NotImplementedError


class HttpSession(BaseSession):
    def __init__(self, *args, **kwargs):
        self.session = requests.Session()
        self.session.proxies = self.proxy
        super(HttpSession, self).__init__(*args, **kwargs)

    @property
    def proxy(self):
        prxy = super(HttpSession, self).proxy
        if prxy:
            prxy = {
                "http": prxy,
                "https": prxy,
            }
        return prxy

    def get(self, url, **kwargs):
        return self.session.get(url=url, **kwargs)

    def head(self, url, **kwargs):
        return self.session.head(url=url, **kwargs)


class AioHttpSession(BaseSession):
    GET_KEY = "get"
    HEAD_KEY = "head"

    def __init__(self):
        super(AioHttpSession, self).__init__()

    @property
    def session(self):
        connector = aiohttp.TCPConnector(limit_per_host=10)
        return aiohttp.ClientSession(connector=connector)

    def _get_call_fn(self, session, fn):
        _call_map = {
            self.GET_KEY: session.get,
            self.HEAD_KEY: session.head,
        }
        return _call_map[fn]

    async def _call_async(self, fn, url, session=None, *args, **kwargs):
        close_flag = False if session else True
        session = session or self.session
        fn = self._get_call_fn(session, fn)
        async with fn(url=url, proxy=self.proxy, *args, **kwargs) as resp:
            raw = await resp.read()
        if close_flag:
            await session.close()
        resp.content = raw
        return resp

    async def _call_many_async(
        self, fn, urls: list, session=None, *args, **kwargs
    ):
        async def _call(counter, *args_, **kwargs_):
            res_ = await self._call_async(*args_, **kwargs_)
            return counter, res_

        close_flag = False if session else True
        session = session or self.session
        tasks = [
            _call(counter=c_, fn=fn, url=x, session=session, *args, **kwargs)
            for c_, x in enumerate(urls)
        ]
        for t_ in asyncio.as_completed(tasks):
            res = await t_
            yield res
        if close_flag:
            await session.close()

    @staticmethod
    async def _call_generator(fn):
        res = []
        async for val in fn:
            res.append(val)
        return res

    def _call_sync(self, fn, *args, **kwargs):
        fn = getattr(self, fn)
        called = fn(*args, **kwargs)
        if asyncio.iscoroutine(called):
            return asyncio.run(called)
        else:
            return asyncio.run(self._call_generator(called))

    get_async: Callable = partialmethod(_call_async, fn=GET_KEY)
    head_async: Callable = partialmethod(_call_async, fn=HEAD_KEY)
    get_many_async: Callable = partialmethod(_call_many_async, fn=GET_KEY)
    head_many_async: Callable = partialmethod(_call_many_async, fn=HEAD_KEY)

    get: Callable = partialmethod(_call_sync, fn="get_async")
    head: Callable = partialmethod(_call_sync, fn="head_async")
    get_many: Callable = partialmethod(_call_sync, fn="get_many_async")
    head_many: Callable = partialmethod(_call_sync, fn="head_many_async")
