from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import BaseSettings, AnyHttpUrl, Field, validator
from pydantic.networks import HttpUrl

BASE_DIR = Path(__file__).resolve().parent.parent


class SettingsCls(BaseSettings):
    BASE_DIR: Path = Field(default=BASE_DIR, const=BASE_DIR)
    BOT_KEY: str
    BOT_AUTO_DELETE: float = 60 * 10
    BOT_READ_TIMEOUT: float = 5
    BOT_WRITE_TIMEOUT: float = 5
    BOT_DOWNLOADER_CACHE_PATH: Path = BASE_DIR.default / "storage/downloader"
    BOT_STORAGE: int
    TD_URL: HttpUrl
    TD_REFRESH_TOKEN: str
    HTTP_PROXY: Optional[AnyHttpUrl] = None
    LOG_LEVEL: str = "WARNING"

    class Config:
        env_prefix = "XOWNBOT__"
        env_file = ".env"

    # noinspection PyMethodParameters
    @validator("BOT_DOWNLOADER_CACHE_PATH", always=True)
    def create__bot_downloader_cache_path(cls, v):
        v.mkdir(parents=True, exist_ok=True)
        return v


@lru_cache
def configure():
    return SettingsCls()


Settings = configure()
