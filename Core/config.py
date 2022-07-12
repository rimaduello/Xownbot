from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import BaseSettings, AnyHttpUrl

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    TELEGRAM_KEY: str
    TELEGRAM_AUTO_DELETE: float = 60 * 10
    TELEGRAM_READ_TIMEOUT: float = 5
    TELEGRAM_WRITE_TIMEOUT: float = 5
    HTTP_PROXY: Optional[AnyHttpUrl] = None
    LOG_LEVEL: str = "WARNING"

    class Config:
        env_prefix = "XOWNBOT__"
        env_file = ".env"


@lru_cache
def configure():
    return Settings()


settings = configure()
