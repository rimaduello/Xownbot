import asyncio
import shutil
from typing import Callable

from utils.types import PathOrStr


class AutoCallMixin(object):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._context = {}

    async def async_auto_call(self, prefix: str, assign: True):
        fn_name_list = [x for x in dir(self) if x.startswith(prefix)]
        fn_name_list = sorted(
            fn_name_list, key=lambda x: int(x.rsplit("__", 1)[-1])
        )
        for fn_name in fn_name_list:
            fn: Callable = getattr(self, fn_name)
            self._context.update(await fn())
        if assign:
            self.assign_from_context()

    def assign_from_context(self):
        for context_key, context_val in self._context.items():
            setattr(self, context_key, context_val)


class Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(
                *args, **kwargs
            )
        return cls._instances[cls]


def size_hr(val, suffix="B"):
    for unit in ["", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi"]:
        if abs(val) < 1024.0:
            return f"{val:3.1f}{unit}{suffix}"
        val /= 1024.0
    return f"{val:.1f}Yi{suffix}"


async def async_move_file(src: PathOrStr, target: PathOrStr):
    await asyncio.to_thread(shutil.move, src, target)


def stripe_www(host: str):
    www = "www."
    if host.startswith("www."):
        host = host[len(www) :]
    return host
