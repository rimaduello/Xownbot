import logging

from Core.config import settings

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(name)s - %(filename)s:%(funcName)s - %(message)s",
    level=logging.getLevelName(settings.LOG_LEVEL),
)


def get_logger(name=None):
    name = name or "anonymous"
    return logging.getLogger(name)
