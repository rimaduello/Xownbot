class DownloadException(Exception):
    pass


class NotSupportedSite(DownloadException):
    def __init__(self, *args):
        super(NotSupportedSite, self).__init__(*args)
        from Download.downloader import DOWNLOADER_MAP

        self.supported = DOWNLOADER_MAP.keys()

    def __str__(self):
        return f"this website is not supported. supported ones are {', '.join(self.supported)}"


class NotSupportedFile(DownloadException):
    def __init__(self, *args):
        super(NotSupportedFile, self).__init__(*args)

    def __str__(self):
        return "this media is not supported"


class DownloadError(DownloadException):
    def __init__(self, error_code, error_msg, *args):
        super(DownloadError, self).__init__(*args)
        self.error_code = error_code
        self.error_msg = error_msg

    def __str__(self):
        return f"error occurred while downloading: {self.error_msg} [code:{self.error_code}]"
