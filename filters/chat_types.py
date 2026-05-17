from aiogram.filters import Filter
from aiogram import Bot, types
import os
from sqlalchemy.ext.asyncio import AsyncSession

from database.orm_query import orm_is_admin

class ChatTypeFilter(Filter):
    def __init__(self, chat_types: list[str]) -> None:
        self.chat_types = chat_types

    async def __call__(self, message: types.Message) -> bool:
        return message.chat.type in self.chat_types
    
class IsAdmin(Filter):
    def __init__(self) -> None:
        admin_ids = os.getenv("ADMIN_IDS", "")
        self.admin_ids = {
            int(admin_id.strip())
            for admin_id in admin_ids.split(",")
            if admin_id.strip().isdigit()
        }

    async def __call__(self, message: types.Message, bot: Bot, session: AsyncSession) -> bool:
        if message.from_user.id in self.admin_ids:
            return True

        if message.from_user.id in getattr(bot, "my_admins_list", []):
            return True

        return await orm_is_admin(session, message.from_user.id)
