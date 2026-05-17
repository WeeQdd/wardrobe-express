import os

from dotenv import load_dotenv
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from common.texts_for_db import categories, description_for_info_pages
from database.models import Base
from database.orm_query import orm_add_banner_description, orm_create_categories


load_dotenv()

database_url = os.getenv("DB_URL") or os.getenv("DB_LITE")

engine = create_async_engine(database_url, echo=True)
session_maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


def _ensure_schema_updates(sync_conn):
    inspector = inspect(sync_conn)

    if "user" in inspector.get_table_names():
        user_columns = {column["name"] for column in inspector.get_columns("user")}
        if "username" not in user_columns:
            sync_conn.execute(text("ALTER TABLE user ADD COLUMN username VARCHAR(100)"))
        if "default_delivery_address" not in user_columns:
            sync_conn.execute(text("ALTER TABLE user ADD COLUMN default_delivery_address TEXT"))
        if "default_delivery_lat" not in user_columns:
            sync_conn.execute(text("ALTER TABLE user ADD COLUMN default_delivery_lat NUMERIC(10, 6)"))
        if "default_delivery_lon" not in user_columns:
            sync_conn.execute(text("ALTER TABLE user ADD COLUMN default_delivery_lon NUMERIC(10, 6)"))
        if "default_pickup_point" not in user_columns:
            sync_conn.execute(text("ALTER TABLE user ADD COLUMN default_pickup_point TEXT"))
        if "active_batch_code" not in user_columns:
            sync_conn.execute(text("ALTER TABLE user ADD COLUMN active_batch_code VARCHAR(64)"))

    if "orders" in inspector.get_table_names():
        order_columns = {column["name"] for column in inspector.get_columns("orders")}
        if "source_url" not in order_columns:
            sync_conn.execute(text("ALTER TABLE orders ADD COLUMN source_url TEXT"))
        if "source_platform" not in order_columns:
            sync_conn.execute(text("ALTER TABLE orders ADD COLUMN source_platform VARCHAR(30)"))
        if "delivery_address" not in order_columns:
            sync_conn.execute(text("ALTER TABLE orders ADD COLUMN delivery_address TEXT"))
        if "delivery_lat" not in order_columns:
            sync_conn.execute(text("ALTER TABLE orders ADD COLUMN delivery_lat NUMERIC(10, 6)"))
        if "delivery_lon" not in order_columns:
            sync_conn.execute(text("ALTER TABLE orders ADD COLUMN delivery_lon NUMERIC(10, 6)"))
        if "nearest_pickup_point" not in order_columns:
            sync_conn.execute(text("ALTER TABLE orders ADD COLUMN nearest_pickup_point TEXT"))
        if "batch_code" not in order_columns:
            sync_conn.execute(text("ALTER TABLE orders ADD COLUMN batch_code VARCHAR(64)"))
        if "service_fee" not in order_columns:
            sync_conn.execute(text("ALTER TABLE orders ADD COLUMN service_fee NUMERIC(10, 2) DEFAULT 0"))
        if "delivery_fee" not in order_columns:
            sync_conn.execute(text("ALTER TABLE orders ADD COLUMN delivery_fee NUMERIC(10, 2) DEFAULT 0"))
        if "total_price" not in order_columns:
            sync_conn.execute(text("ALTER TABLE orders ADD COLUMN total_price NUMERIC(10, 2) DEFAULT 0"))


async def create_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_schema_updates)

    async with session_maker() as session:
        await orm_create_categories(session, categories)
        await orm_add_banner_description(session, description_for_info_pages)


async def drop_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
