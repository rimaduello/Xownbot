import asyncio
import mimetypes
from math import ceil
from pathlib import Path
from types import MethodType
from typing import BinaryIO

from aiohttp import ClientSession, FormData
from multidict import CIMultiDict

from Core.config import Settings
from Core.logger import get_logger

logger = get_logger("BOT")


class TeleDriveClient:
    BASE_PATH = "/api/v1"
    PATH = {
        "me": "/auth/me",
        "refresh_token": "/auth/refreshToken",
        "upload": "/files/upload",
        "retrieve": "/files",
    }
    DEFAULT_HEADERS = {"Content-Type": "application/json"}
    access_token = None

    def __init__(self, end_point=None, refresh_token=None):
        self.END_POINT = end_point or Settings.TD_URL
        self.PATH = {k: self.BASE_PATH + v for k, v in self.PATH.items()}
        self.refresh_token = refresh_token or Settings.TD_REFRESH_TOKEN

    async def retrieve(self, file_uid, raw=False):
        path = self.PATH["retrieve"]
        path = f"{path}/{file_uid}"
        params = dict(raw=1 if raw else 0, dl=0 if raw else 1)
        client = await self.get_client(auth=True)
        logger.info(f"retrieve file {file_uid}")
        async with client as cl_:
            async with cl_.get(path, params=params) as req:
                resp = await req.json()
        logger.debug(f"retrieved file {file_uid}:{resp}")
        return resp

    async def upload(self, file: BinaryIO, name=None, mime_type=None):
        chunk_size = 512 * 1024
        info = self.get_file_info(file)
        params = dict(
            name=name or info["name"],
            size=info["size"],
            mime_type=mime_type or info["mime_type"],
            part=0,
        )
        params["total_part"] = ceil(params["size"] / chunk_size)
        path = self.PATH["upload"]
        logger.info(f"uploading: {params}")
        client = await self.get_client(auth=True)
        async with client as cl_:
            req_ = await self._upload_chunk(
                client=cl_,
                path=path,
                file=file,
                params=params,
                part_no=0,
                chunk_size=chunk_size,
            )
            file_uid = req_["file"]["id"]
            logger.debug(f"first chunk uploaded: {file_uid}")
            if params["total_part"] > 1:
                logger.debug(f"file is big! {file_uid}:{params}")
                path = f"{path}/{file_uid}"
                tasks_ = [
                    self._upload_chunk(
                        client=cl_,
                        path=path,
                        file=file,
                        params=params,
                        part_no=x,
                        chunk_size=chunk_size,
                    )
                    for x in range(1, params["total_part"])
                ]
                await asyncio.gather(*(tasks_[:-1]))
                await tasks_[-1]
        return file_uid

    async def get_client(
        self, auth=True, extra_headers=None, no_default_header=False
    ) -> ClientSession:
        extra_headers = extra_headers or {}
        headers = {**({} if no_default_header else self.DEFAULT_HEADERS)}
        headers.update(extra_headers)
        cl_ = ClientSession(base_url=self.END_POINT, headers=headers)
        logger.debug(f"created client:{cl_.__dict__}")
        logger.debug(f"client headers:{headers}")
        if Settings.HTTP_PROXY:

            async def _request(self_, *args, **kwargs):
                kwargs["proxy"] = Settings.HTTP_PROXY
                return await self_.old_request(*args, **kwargs)

            # noinspection PyProtectedMember
            cl_.old_request = cl_._request
            cl_._request = MethodType(_request, cl_)
            logger.debug(f"patched client proxy {Settings.HTTP_PROXY}")
        if auth:
            await self.authorize(client=cl_)
        return cl_

    @staticmethod
    def get_file_info(file: BinaryIO):
        file_path = Path(file.name)
        info = dict(
            name=file_path.name,
            size=file_path.stat().st_size,
            mime_type=mimetypes.guess_type(file_path)[0],
        )
        logger.debug(f"file info for {file_path}:{info}")
        return info

    async def authorize(self, client: ClientSession):
        client.headers[
            "Authorization"
        ] = f"Bearer {await self.get_bearer(client)}"
        logger.debug("authorized client")

    async def get_bearer(self, client: ClientSession):
        me_ = await client.head(url=self.PATH["me"])
        if me_.status == 401:
            self.access_token = await self._bearer(client)
        return self.access_token

    @staticmethod
    async def _upload_chunk(
        client: ClientSession,
        path,
        file: BinaryIO,
        params,
        part_no,
        chunk_size,
    ):
        data = FormData()
        file.seek(part_no * chunk_size)
        data.add_field("upload", file.read(chunk_size))
        params = {**params, "part": part_no}
        logger.debug(f"uploading chunk: {params}")
        headers_backup = client.headers
        client._default_headers = CIMultiDict({})
        async with client.post(path, params=params, data=data) as req:
            resp = await req.json()
        client._default_headers = CIMultiDict(headers_backup)
        logger.debug(f"uploaded chunk {params}. response:{resp}")
        return resp

    async def _bearer(self, client: ClientSession):
        token_ = await client.post(
            self.PATH["refresh_token"],
            json={"refreshToken": self.refresh_token},
            headers=self.DEFAULT_HEADERS,
        )
        token_ = await token_.json()
        return token_["accessToken"]
