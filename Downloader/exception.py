from utils.types import URLOrStr


class BaseDownloaderException(Exception):
    pass


class BAInfoError(BaseDownloaderException):
    def __init__(self, url: URLOrStr, msg: str, *args):
        super(BaseDownloaderException, self).__init__(*args)
        self.url = url
        self.msg = msg

    def __str__(self) -> str:
        return f"error getting info from {self.url}:{self.msg}"


class Aria2Error(BaseDownloaderException):
    def __init__(self, code: str, msg: str, *args):
        super(BaseDownloaderException, self).__init__(*args)
        self.code = code
        self.msg = msg

    def __str__(self) -> str:
        return f"error while downloading: {self.msg}({self.code})"
