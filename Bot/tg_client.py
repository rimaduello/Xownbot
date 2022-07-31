import asyncio

from telethon.client import TelegramClient
from Core.config import Settings, BASE_DIR
from FastTelethonhelper import fast_upload

TELEGRAM_SESSION_PATH = BASE_DIR / "storge/tg_session"
TELEGRAM_CONFIG_PATH = BASE_DIR / "storge/tg_config.json"


class TgClient:
    async def upload(self, file, **kwargs):
        client_ = self.tg_client
        async with client_:
            uploaded = await fast_upload(client_, file)
            msg = await client_.send_message(
                self.storage_entity, file=uploaded
            )
        return msg

    async def delete(self, message_id: str):
        client_ = self.tg_client
        async with client_:
            msg = await client_.delete_messages(
                entity=self.storage_entity, message_ids=message_id
            )
        return msg

    @classmethod
    async def create_session(cls):
        if not TELEGRAM_SESSION_PATH.exists():
            TELEGRAM_SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
            client_ = cls().tg_client
            async with client_:
                pass

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
            "api_id": Settings.CLIENT_ID,
            "api_hash": Settings.CLIENT_HASH,
            "session": str(TELEGRAM_SESSION_PATH),
            "proxy": prx_,
        }
        return conf_

    @property
    def tg_client(self):
        return TelegramClient(**self.configuration_data)

    @property
    def storage_entity(self):
        return Settings.CLIENT_STORAGE


asyncio.get_event_loop().run_until_complete(TgClient.create_session())