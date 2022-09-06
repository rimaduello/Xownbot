from __future__ import annotations

import urllib.parse
from ctypes import Union
from pathlib import Path
from typing import TypedDict, List
from uuid import uuid4

import aiofiles

from Core.config import Settings
from Core.db import Mongo
from FileServer.exception import FileAlreadyExists, FileNotExists
from utils.helpers import size_hr


class FileResultType(TypedDict):
    name: str
    path: Path
    url: str
    size: Union[int, str]
    created: int


class FileObj:
    db_file_id_key = "file_id"

    def __init__(self, user_id, user_data):
        self.user_id = user_id
        self.user_data = user_data

    async def save_file(self, file: Path):
        write_path = self.abs_path(file.name)
        await self._save_file(file, write_path)
        return self.abs_link(file.name)

    def get_file(self, file_name, human_readable=True) -> FileResultType:
        data_ = {
            "name": file_name,
            "path": self.abs_path(file_name),
            "url": self.abs_link(file_name),
        }
        state_ = data_["path"].stat()
        size_ = state_.st_size * 1024
        if human_readable:
            size_ = size_hr(size_)
        data_["size"] = size_
        data_["created"] = state_.st_ctime
        return FileResultType(**data_)

    def list_files(self, human_readable=True) -> List[FileResultType]:
        file_list = []
        for f_ in self.abs_dir.iterdir():
            if not f_.is_file():
                continue
            file_list.append(
                self.get_file(f_.name, human_readable=human_readable)
            )
        return file_list

    def del_file(self, file_name):
        u_ = self.abs_path(file_name)
        self._del_file(u_)

    @property
    def user_local_id(self):
        return self.user_data[self.db_file_id_key]

    @property
    def abs_dir(self):
        u_ = self.user_local_id
        return self._get_abs_dir(u_)

    def abs_path(self, file_name):
        u_ = self.abs_dir
        return u_ / file_name

    def abs_link(self, file_name):
        u_ = self.user_local_id
        return self._get_abs_link(u_, file_name)

    @staticmethod
    def _get_abs_dir(uid: str):
        return Settings.FILESERVER_ROOT / uid

    @staticmethod
    def _get_abs_link(uid: str, file_name: str):
        file_path = "/".join([uid, file_name])
        file_path = urllib.parse.quote(file_path)
        return f"{Settings.FILESERVER_URL}/{file_path}"

    @staticmethod
    async def _save_file(file_read_path: Path, file_write_path: Path):
        if file_write_path.is_file():
            raise FileAlreadyExists(file_write_path)
        if not file_read_path.is_file():
            raise FileNotExists(file_read_path)
        chunk_size = 512 * 1024
        async with aiofiles.open(file_read_path, "rb") as f_read:
            async with aiofiles.open(file_write_path, "wb") as f_write:
                while True:
                    data_ = await f_read.read(chunk_size)
                    if not data_:
                        break
                    await f_write.write(data_)

    @staticmethod
    def _del_file(file_path: Path, missing_ok=True):
        file_path.unlink(missing_ok)

    @classmethod
    async def user(cls, user_id, create=True) -> FileObj:
        cl_ = Mongo.get_collection(Settings.MONGO_COLLECTION_FILES)
        user_data = await (cl_.find_one({"user_id": user_id}))
        if user_data is None:
            if create:
                dir_name = uuid4().hex
                dir_abs = cls._get_abs_dir(dir_name)
                dir_abs.mkdir(parents=True, exist_ok=True)
                user_data = {"user_id": user_id, cls.db_file_id_key: dir_name}
                await cl_.insert_one(user_data)
            else:
                raise KeyError("user file path not found in db")

        return cls(user_id=user_id, user_data=user_data)
