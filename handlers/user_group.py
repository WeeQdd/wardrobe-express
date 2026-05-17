from string import punctuation

from aiogram import Bot, Router, types
from aiogram.filters import Command
from sqlalchemy.ext.asyncio import AsyncSession

from database.orm_query import orm_sync_chat_admins
from filters.chat_types import ChatTypeFilter


user_group_router = Router()
user_group_router.message.filter(ChatTypeFilter(["group", "supergroup"]))
user_group_router.edited_message.filter(ChatTypeFilter(["group", "supergroup"]))


restricted_words = {"кабан", "хомяк", "выхухоль"}


def clean_text(text: str) -> str:
    return text.translate(str.maketrans("", "", punctuation))


async def sync_chat_admins(bot: Bot, session: AsyncSession, chat_id: int):
    admins = await bot.get_chat_administrators(chat_id)
    admin_ids = {
        member.user.id
        for member in admins
        if member.status in {"creator", "administrator"}
    }

    current_admins = set(getattr(bot, "my_admins_list", []))
    bot.my_admins_list = list(current_admins | admin_ids)
    await orm_sync_chat_admins(session, chat_id, admin_ids)
    return admin_ids


@user_group_router.message(Command("admin"))
async def get_admins(message: types.Message, bot: Bot, session: AsyncSession):
    admin_ids = await sync_chat_admins(bot, session, message.chat.id)
    if message.from_user.id in admin_ids:
        await message.delete()


@user_group_router.edited_message()
@user_group_router.message()
async def cleaner(message: types.Message, bot: Bot, session: AsyncSession):
    await sync_chat_admins(bot, session, message.chat.id)

    if not message.text:
        return

    words = clean_text(message.text.lower()).split()
    if restricted_words.intersection(words):
        await message.answer(f"{message.from_user.first_name}, соблюдайте порядок")
        await message.delete()
