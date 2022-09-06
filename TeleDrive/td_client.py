import asyncio

import FastTelethonhelper
from telethon.client import TelegramClient

from Core.config import Settings
from Core.logger import get_logger, call_log

TELEGRAM_SESSION_PATH = Settings.BASE_DIR / "storage/tg_session"

logger = get_logger(__name__)


class TeleDriveClient:
    STORAGE_ENTITY = Settings.BOT_STORAGE

    @property
    def configuration_data(self):
        prx_ = Settings.HTTP_PROXY
        if prx_:
            prx_ = {
                "proxy_type": "http",
                "addr": prx_.host,
                "port": prx_.port,
                "username": prx_.user,
                "password": prx_.password,
            }
        conf_ = {
            "api_id": Settings.TD_API_ID,
            "api_hash": Settings.TD_API_HASH,
            "session": str(TELEGRAM_SESSION_PATH),
            "proxy": prx_,
        }
        return conf_

    @property
    def tg_client(self) -> TelegramClient:
        cl_ = TelegramClient(**self.configuration_data)
        return cl_

    @call_log(logger)
    async def upload(self, file_path):
        client_ = self.tg_client
        async with client_:
            uploaded = await FastTelethonhelper.fast_upload(client_, file_path)
            res_ = await client_.send_message(
                self.STORAGE_ENTITY, file=uploaded
            )
        return res_

    @call_log(logger)
    async def download(self, msg_id, dir_path):
        dir_path = dir_path if dir_path.endswith("/") else f"{dir_path}/"
        client_ = self.tg_client
        async with client_:
            msg_ = client_.iter_messages(
                entity=self.STORAGE_ENTITY,
                min_id=msg_id - 1,
                max_id=msg_id + 1,
            )
            async for m_ in msg_:
                res_ = await FastTelethonhelper.fast_download(
                    client_, m_, download_folder=dir_path
                )
        return res_

    @classmethod
    @call_log(logger)
    async def create_session(cls):
        if not TELEGRAM_SESSION_PATH.exists():
            TELEGRAM_SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
            client_ = cls().tg_client
            async with client_:
                pass


asyncio.get_event_loop().run_until_complete(TeleDriveClient.create_session())
