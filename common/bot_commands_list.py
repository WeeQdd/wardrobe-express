from aiogram.types import BotCommand


private = [
    BotCommand(command="start", description="Открыть главное меню"),
    BotCommand(command="admin", description="Панель администратора"),
    BotCommand(command="orders", description="Список заказов"),
]

group = [
    BotCommand(command="id", description="Узнать id чата"),
]
