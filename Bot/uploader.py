import asyncio

from telethon.client import TelegramClient

from Core.config import settings, BASE_DIR

TELEGRAM_SESSION_PATH = BASE_DIR / "storge/tg_session"
TELEGRAM_CONFIG_PATH = BASE_DIR / "storge/tg_config.json"


def _configuration():
    prx_ = settings.HTTP_PROXY
    if prx_:
        prx_ = {
            "proxy_type": "http",
            "addr": prx_.host,
            "port": prx_.port,
            "username": prx_.user,
            "password": prx_.password,
        }
    conf_ = {
        "api_id": settings.CLIENT_ID,
        "api_hash": settings.CLIENT_HASH,
        "session": str(TELEGRAM_SESSION_PATH),
        "proxy": prx_,
    }
    return conf_


def _get_client():
    return TelegramClient(**_configuration())


def _get_entity():
    return settings.CLIENT_STORAGE


async def upload(file):
    client_ = _get_client()
    async with client_:
        msg = await client_.send_file(entity=_get_entity(), file=file)
    return msg


async def delete(message_id: str):
    client_ = _get_client()
    async with client_:
        msg = await client_.delete_messages(
            entity=_get_entity(), message_ids=message_id
        )
    return msg


async def create_session():
    if not TELEGRAM_SESSION_PATH.exists():
        TELEGRAM_SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
        client_ = _get_client()
        async with client_:
            pass


asyncio.get_event_loop().run_until_complete(create_session())
