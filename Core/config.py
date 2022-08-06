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
    MONGO_COLLECTION_FILES: str = "files"
    FILESERVER_ROOT: Path = "storage/fileserver"
    FILESERVER_URL: HttpUrl
    FILESERVER_AUTO_DELETE: int = 60 * 60
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
    @validator("FILESERVER_ROOT", always=True)
    def generate__fileserver_root(cls, v, values):
        return values["BASE_DIR"] / v

    # noinspection PyMethodParameters
    @validator("FILESERVER_URL", always=True)
    def process__fileserver_url(cls, v):
        return v.rstrip("/")


@lru_cache
def configure():
    return SettingsCls()


Settings = configure()
