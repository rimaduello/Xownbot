import logging

from Core.config import Settings


def get_logger_no(log_level):
    return logging.getLevelName(log_level)


def get_logger(name=None):
    name = name or "anonymous"
    return logging.getLogger(name)


logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(name)s - %(filename)s:%(funcName)s - %(message)s",
    level=get_logger_no(Settings.LOG_LEVEL),
)
