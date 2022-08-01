import asyncio
import mimetypes
from io import BytesIO
from math import ceil
from pathlib import Path
from types import MethodType
from typing import BinaryIO, Union, Tuple

from aiohttp import (
    ClientSession,
    FormData,
    TCPConnector,
    ClientResponse,
    ContentTypeError,
)
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
        "create": "/files",
        "settings": "/users/me/settings",
    }
    DEFAULT_HEADERS = {"Content-Type": "application/json"}
    access_token = None

    def __init__(self, end_point=None, refresh_token=None):
        self.END_POINT = end_point or Settings.TD_URL
        self.PATH = {k: self.BASE_PATH + v for k, v in self.PATH.items()}
        self.refresh_token = refresh_token or Settings.TD_REFRESH_TOKEN

    async def retrieve(self, file_uid):
        client = await self.get_client(auth=True)
        async with client as cl_:
            resp = await self._retrieve(cl_, file_uid, raw=False)
        return resp

    async def download(self, file_uid, save_to: BinaryIO):
        client = await self.get_client()
        async with client as cl_:
            resp = await self._download(file_uid=file_uid, client=cl_)
            async for r_ in resp.content.iter_chunked(512 * 1024):
                save_to.write(r_)

    async def upload(self, file: BinaryIO, name=None, mime_type=None):
        sem = asyncio.Semaphore(Settings.TD_THROTTLING)

        async def __upload_chunk(part_no_):
            async with sem:
                return await self._upload_chunk(
                    client=cl_,
                    path=path,
                    file=file,
                    params=params,
                    part_no=part_no_,
                    chunk_size=chunk_size,
                )

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
            req_ = await __upload_chunk(0)
            file_uid = req_["file"]["id"]
            logger.debug(f"first chunk uploaded: {file_uid}")
            if params["total_part"] > 1:
                logger.debug(f"file is big! {file_uid}:{params}")
                path = f"{path}/{file_uid}"
                tasks_ = [
                    __upload_chunk(part_no_=x)
                    for x in range(1, params["total_part"])
                ]
                await asyncio.gather(*(tasks_[:-1]))
                await tasks_[-1]
        return file_uid

    async def create(self, message_id):
        params = dict(messageId=message_id)
        path = self.PATH["create"]
        client = await self.get_client(auth=True)
        async with client as cl_:
            storage_id = await self._storage_id(cl_)
            data = {
                "file": {
                    "forward_info": storage_id.replace("_", str(message_id))
                }
            }
            logger.info(f"creating: {params}-{data}")
            _, resp = await self._request(
                "post", path, cl_, json=data, params=params
            )
        logger.info(f"created file {resp['file']['id']}")
        return resp

    async def get_client(
        self, auth=True, extra_headers=None, no_default_header=False
    ) -> ClientSession:
        extra_headers = extra_headers or {}
        headers = {**({} if no_default_header else self.DEFAULT_HEADERS)}
        headers.update(extra_headers)
        connector = TCPConnector(limit_per_host=Settings.TD_THROTTLING)
        cl_ = ClientSession(
            base_url=self.END_POINT, headers=headers, connector=connector
        )
        # noinspection DuplicatedCode
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

    async def _retrieve(self, client: ClientSession, file_uid, raw):
        path = self.PATH["retrieve"]
        path = f"{path}/{file_uid}"
        dl = not raw
        params = dict(raw=int(raw), dl=int(dl))
        logger.info(f"retrieve file {file_uid}:{params}")
        resp, cont = await self._request(
            "get", path, client, close=dl, content=dl, params=params
        )
        logger.debug(f"retrieved file {cont}")
        return resp if raw else cont

    async def _upload_chunk(
        self,
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
        _, resp = await self._request(
            "post", path, client, params=params, data=data
        )
        client._default_headers = CIMultiDict(headers_backup)
        logger.debug(f"uploaded chunk {params}. response:{resp}")
        return resp

    async def _bearer(self, client: ClientSession):
        _, resp = await self._request(
            "post",
            self.PATH["refresh_token"],
            client,
            json={"refreshToken": self.refresh_token},
            headers=self.DEFAULT_HEADERS,
        )
        return resp["accessToken"]

    async def _storage_id(self, client):
        _, resp = await self._request("get", self.PATH["settings"], client)
        storage_id = resp["user"]["settings"]["saved_location"]
        logger.debug(f"storge id is: {storage_id}")
        return storage_id

    async def _download(
        self, file_uid, client: ClientSession
    ) -> ClientResponse:
        resp = await self._retrieve(client, file_uid, raw=True)
        return resp

    @staticmethod
    async def _request(
        type_,
        path,
        client: ClientSession,
        close=True,
        content=True,
        jsonify=True,
        **kwargs,
    ) -> Tuple[ClientResponse, Union[bytes, dict]]:
        fn_ = {
            "get": client.get,
            "post": client.post,
        }[type_]
        req_: ClientResponse = await fn_(path, **kwargs)
        data = None
        if content:
            data = await req_.read()
            if jsonify:
                try:
                    data = await req_.json()
                except ContentTypeError as e_:
                    logger.error(f"non json response content: {data}")
                    raise e_
        if close:
            req_.close()
        return req_, data
