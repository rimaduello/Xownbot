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
    BOT_POOL_TIMEOUT: float = 5
    BOT_DOWNLOADER_CACHE_PATH: Path = "storage/downloader"
    BOT_USERS_FILE: Path = "storage/users"
    BOT_STORAGE: int
    TD_API_ID: str
    TD_API_HASH: str
    SSB_URL: HttpUrl = "https://api.streamsb.com"
    SSB_TOKEN: str
    SSB_FILE_URL: HttpUrl = "https://sbthe.com"
    DOWNLOADER_THROTTLING: int = 10
    HTTP_PROXY: Optional[AnyHttpUrl] = None
    LOG_LEVEL: str = "WARNING"

    class Config:
        env_prefix = "XOWNBOT__"
        env_file = ".env"

    # noinspection PyMethodParameters
    @validator("BOT_DOWNLOADER_CACHE_PATH", always=True)
    def generate__bot_downloader_cache_path(cls, v, values):
        v = values["BASE_DIR"] / v
        return v

    # noinspection PyMethodParameters
    @validator("BOT_DOWNLOADER_CACHE_PATH", always=True)
    def create__bot_downloader_cache_path(cls, v):
        v.mkdir(parents=True, exist_ok=True)
        return v

    # noinspection PyMethodParameters
    @validator("BOT_USERS_FILE", always=True)
    def generate__bot_users_file(cls, v, values):
        v = values["BASE_DIR"] / v
        return v


@lru_cache
def configure():
    return SettingsCls()


Settings = configure()
