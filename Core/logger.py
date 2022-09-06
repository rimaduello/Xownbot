import functools
import inspect
import logging
import uuid

from Core.config import Settings


def get_logger_no(log_level):
    return logging.getLevelName(log_level)


def get_logger(name=None):
    name = name or "anonymous"
    _logger = logging.getLogger(name)
    _logger.setLevel(get_logger_no(Settings.LOG_LEVEL))
    return _logger


def call_log(
    logger: logging.Logger,
    enter_level=logging.DEBUG,
    exit_level=logging.DEBUG,
    args_level=logging.DEBUG,
    ret_level=logging.DEBUG,
):
    def _decorator(func):
        func_logger_kwarg = "_function_logger"

        def _prep():
            _uid = uuid.uuid4().hex
            fn_name = func.__str__().split(" ", 2)[1]
            _fn_logger = logger.getChild(f"{fn_name}({_uid})")
            return _uid, _fn_logger

        def _pre_call(_fn_logger, *args, **kwargs):
            _fn_logger.log(enter_level, "enter")
            _fn_logger.log(args_level, f"args={args} kwargs={kwargs}")

        def _post_call(_fn_logger, _ret):
            _fn_logger.log(ret_level, f"return {_ret}")
            _fn_logger.log(exit_level, "exit")

        def _logger_as_arg(_fn_logger):
            _ret = {}
            if func_logger_kwarg in inspect.signature(func).parameters.keys():
                _ret[func_logger_kwarg] = _fn_logger
            return _ret

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                _uid, _fn_logger = _prep()
                _pre_call(_fn_logger, *args, **kwargs)
                _ret = await func(
                    *args, **kwargs, **_logger_as_arg(_fn_logger)
                )
                _post_call(_fn_logger, _ret)
                return _ret

        else:

            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                _uid, _fn_logger = _prep()
                _pre_call(_fn_logger, *args, **kwargs)
                _ret = func(*args, **kwargs, **_logger_as_arg(_fn_logger))
                _post_call(_fn_logger, _ret)
                return _ret

        wrapper: func
        return wrapper

    return _decorator


logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
