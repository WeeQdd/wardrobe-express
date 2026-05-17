import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from dotenv import find_dotenv, load_dotenv

from common.bot_commands_list import group, private
from database.engine import create_db, session_maker
from database.orm_query import orm_get_admin_ids
from handlers.admin_private import admin_router
from handlers.user_group import user_group_router
from handlers.user_private import user_private_router
from middlewares.db import DataBaseSession


load_dotenv(find_dotenv())
logging.basicConfig(level=logging.INFO)


bot = Bot(
    token=os.getenv("TOKEN"),
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
bot.my_admins_list = []

dp = Dispatcher()
dp.include_router(user_private_router)
dp.include_router(user_group_router)
dp.include_router(admin_router)


async def on_startup():
    await create_db()
    async with session_maker() as session:
        bot.my_admins_list = list(await orm_get_admin_ids(session))


async def on_shutdown():
    logging.info("Bot shutdown")


async def main():
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    dp.update.middleware(DataBaseSession(session_pool=session_maker))

    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_my_commands(commands=private, scope=types.BotCommandScopeAllPrivateChats())
    await bot.set_my_commands(commands=group, scope=types.BotCommandScopeAllGroupChats())
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


asyncio.run(main())
