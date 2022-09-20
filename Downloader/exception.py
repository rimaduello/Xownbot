from utils.types import URLOrStr, urlorstr_2_url


class DownloaderException(Exception):
    pass


class NotSupportedSite(DownloaderException):
    def __init__(self, url: URLOrStr, *args):
        super(NotSupportedSite, self).__init__(*args)
        from Downloader.extractor import SUPPORTED_SITES

        self.url = urlorstr_2_url(url)
        self.supported = SUPPORTED_SITES

    def __str__(self):
        return f"{self.url.host} is not supported. supported ones are {', '.join(self.supported)}"


class NotSupportedFile(DownloaderException):
    def __init__(self, *args):
        super(NotSupportedFile, self).__init__(*args)

    def __str__(self):
        return "this media is not supported"


class DownloaderError(DownloaderException):
    def __init__(self, error_code, error_msg, *args):
        super(DownloaderError, self).__init__(*args)
        self.error_code = error_code
        self.error_msg = error_msg

    def __str__(self):
        return f"error occurred while downloading: {self.error_msg} [code:{self.error_code}]"
