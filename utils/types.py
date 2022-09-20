from pathlib import Path
from typing import Union

from yarl import URL

URLOrStr = Union[str, URL]
PathOrStr = Union[str, Path]


def urlorstr_2_url(val: URLOrStr):
    if isinstance(val, str):
        val = URL(val)
    return val


def pathorstr_2_path(val: PathOrStr):
    if isinstance(val, str):
        val = Path(val)
    return val
