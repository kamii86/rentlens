from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from rentlens.config import DATABASE_URL

engine: AsyncEngine = create_async_engine(DATABASE_URL)