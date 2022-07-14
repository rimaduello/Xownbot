from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import BaseSettings, AnyHttpUrl

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    BOT_KEY: str
    BOT_AUTO_DELETE: float = 60 * 10
    BOT_READ_TIMEOUT: float = 5
    BOT_WRITE_TIMEOUT: float = 5
    CLIENT_ID: str
    CLIENT_HASH: str
    CLIENT_STORAGE: int
    HTTP_PROXY: Optional[AnyHttpUrl] = None
    LOG_LEVEL: str = "WARNING"

    class Config:
        env_prefix = "XOWNBOT__"
        env_file = ".env"


@lru_cache
def configure():
    return Settings()


settings = configure()
