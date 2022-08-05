from io import BytesIO
from pathlib import Path
from types import MethodType
from typing import Union, BinaryIO

from aiohttp import ClientSession, FormData, ClientResponse, ContentTypeError

from Core.config import Settings
from Core.logger import get_logger
import urllib.parse

logger = get_logger("SSB")


class StreamSBClient:
    BASE_PATH = "/api"
    PATH = {"get_upload_server": "/upload/server"}
    DEFAULT_HEADERS = {}
    DEFAULT_PARAMS = {}

    def __init__(self, end_point=None, access_token=None):
        self.END_POINT = end_point or Settings.SSB_URL
        self.PATH = {k: self.BASE_PATH + v for k, v in self.PATH.items()}
        self.access_token = access_token or Settings.SSB_TOKEN
        self.DEFAULT_PARAMS["key"] = self.access_token

    async def get_client(
        self, extra_headers=None, no_default_header=False, end_point=None
    ) -> ClientSession:
        extra_headers = extra_headers or {}
        headers = {**({} if no_default_header else self.DEFAULT_HEADERS)}
        headers.update(extra_headers)
        cl_ = ClientSession(
            base_url=(end_point or self.END_POINT), headers=headers
        )
        # noinspection DuplicatedCode
        logger.debug(
            f"created client: header={headers} end_point={end_point} {cl_.__dict__}"
        )
        if Settings.HTTP_PROXY:

            async def _request(self_, *args, **kwargs):
                kwargs["proxy"] = Settings.HTTP_PROXY
                return await self_.old_request(*args, **kwargs)

            # noinspection PyProtectedMember
            cl_.old_request = cl_._request
            cl_._request = MethodType(_request, cl_)
            logger.debug(f"patched client proxy {Settings.HTTP_PROXY}")
        return cl_

    async def upload(self, file: Union[BytesIO, BinaryIO]):
        logger.info(f"upload request: {file.name}")
        upload_url = await self.get_upload_server()
        upload_url = urllib.parse.urlparse(upload_url)
        client_ = await self.get_client(
            end_point=urllib.parse.urlunsplit(
                (upload_url.scheme, upload_url.netloc, "/", None, None)
            )
        )
        data = FormData()
        data.add_field("api_key", self.access_token)
        data.add_field("json", "1")
        data.add_field("file", file, filename=Path(file.name).name)
        async with client_ as cl_:
            _, resp = await self._request(
                type_="post", path=upload_url.path, client=cl_, data=data
            )
        logger.info(f"upload request done: {file.name}")
        return resp

    async def get_upload_server(self):
        path = self.PATH["get_upload_server"]
        client_ = await self.get_client()
        params = self.DEFAULT_PARAMS
        async with client_ as cl_:
            _, res = await self._request(
                type_="get", path=path, client=cl_, params=params
            )
        logger.info(f"upload server is: {res}")
        return res

    @staticmethod
    async def _request(type_, path, client: ClientSession, **kwargs):
        fn_ = {
            "get": client.get,
            "post": client.post,
        }[type_]
        req_: ClientResponse
        logger.debug(f"{type_} request: path={path} kwargs={kwargs}")
        async with fn_(path, **kwargs) as req_:
            data = await req_.read()
            try:
                data = (await req_.json())["result"]
            except ContentTypeError as e_:
                logger.error(f"non json response content: {data}")
                raise e_
        logger.debug(f"{type_} request done: {path} {req_.status} {data}")
        return req_, data

    @staticmethod
    def get_file_url(file_id):
        path_ = f"/{file_id}.html"
        return urllib.parse.urljoin(Settings.SSB_FILE_URL, path_)
