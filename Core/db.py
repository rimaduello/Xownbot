from functools import lru_cache

import motor.motor_asyncio
from motor.core import AgnosticCollection

from Core.config import Settings


class MongoDB:
    uri = Settings.MONGO_URI
    mongo_db = Settings.MONGO_DB

    @property
    def client(self):
        return motor.motor_asyncio.AsyncIOMotorClient(Settings.MONGO_URI)

    @property
    def db(self) -> motor.motor_asyncio.AsyncIOMotorCollection:
        return self.client[self.mongo_db]

    def get_collection(self, collection_name) -> AgnosticCollection:
        return self.db[collection_name]

    @staticmethod
    async def create_index(
        collection: AgnosticCollection, index_name, **kwargs
    ):
        if index_name not in {
            x["name"] async for x in collection.list_indexes()
        }:
            await collection.create_index(index_name, **kwargs)


@lru_cache
def _create_client():
    return MongoDB()


Mongo = _create_client()
