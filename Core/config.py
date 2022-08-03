from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import BaseSettings, AnyHttpUrl, Field, validator
from pydantic.networks import HttpUrl, AnyUrl

BASE_DIR = Path(__file__).resolve().parent.parent


class SettingsCls(BaseSettings):
    BASE_DIR: Path = Field(default=BASE_DIR, const=BASE_DIR)
    BOT_KEY: str
    BOT_AUTO_DELETE: float = 60 * 10
    BOT_READ_TIMEOUT: float = 5
    BOT_WRITE_TIMEOUT: float = 5
    BOT_POOL_TIMEOUT: float = 5
    BOT_DOWNLOADER_CACHE_PATH: Path = "storage/downloader"
    BOT_STORAGE: int
    TD_API_ID: str
    TD_API_HASH: str
    MONGO_URI: AnyUrl
    MONGO_DB: str = "xownbot"
    MONGO_COLLECTION_USER: str = "users"
    SSB_URL: HttpUrl = "https://api.streamsb.com"
    SSB_TOKEN: str
    SSB_FILE_URL: HttpUrl = "https://sbthe.com"
    DOWNLOADER_THROTTLING: int = 10
    HTTP_PROXY: Optional[AnyHttpUrl] = None
    LOG_LEVEL: str = "WARNING"

    class Config:
        env_prefix = "XOWNBOT__"
        env_file = ".env"


@lru_cache
def configure():
    return SettingsCls()


Settings = configure()
