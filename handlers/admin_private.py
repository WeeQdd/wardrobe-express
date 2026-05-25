from html import escape

from aiogram import F, Router, types
from aiogram.filters import Command, StateFilter, or_f
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession

from common.texts_for_db import description_for_info_pages
from database.orm_query import (
    orm_add_item,
    orm_change_banner_image,
    orm_delete_item,
    orm_delete_order,
    orm_get_categories,
    orm_get_client_profile,
    orm_get_clients,
    orm_get_item,
    orm_get_items,
    orm_get_order,
    orm_get_orders,
    orm_get_user_by_db_id,
    orm_update_item,
    orm_update_order_status,
)
from filters.chat_types import ChatTypeFilter, IsAdmin
from kbds.inline import (
    get_admin_order_detail_btns,
    get_admin_order_list_btns,
    get_callback_btns,
    get_client_list_btns,
    get_order_status_emoji,
)
from kbds.reply import get_keyboard
from services.pricing import summarize_order_totals


admin_router = Router()
admin_router.message.filter(ChatTypeFilter(["private"]), IsAdmin())


ORDER_STATUS_LABELS = {
    "new": "\u041d\u043e\u0432\u044b\u0439",
    "confirmed": "\u041f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d",
    "awaiting_payment": "\u041e\u0436\u0438\u0434\u0430\u0435\u0442 \u043e\u043f\u043b\u0430\u0442\u0443",
    "paid": "\u041e\u043f\u043b\u0430\u0447\u0435\u043d",
    "purchased": "\u0412\u044b\u043a\u0443\u043f\u043b\u0435\u043d",
    "at_warehouse": "\u041d\u0430 \u0441\u043a\u043b\u0430\u0434\u0435",
    "in_transit": "\u0412 \u043f\u0443\u0442\u0438",
    "ready_for_pickup": "\u0413\u043e\u0442\u043e\u0432 \u043a \u0432\u044b\u0434\u0430\u0447\u0435",
    "done": "\u0412\u044b\u0434\u0430\u043d",
    "cancelled": "\u041e\u0442\u043c\u0435\u043d\u0435\u043d",
}


class AdminMessageToClient(StatesGroup):
    text = State()


ADMIN_BTN_ADD_ITEM = "➕ Добавить товар"
ADMIN_BTN_CATALOG = "🛍 Ассортимент"
ADMIN_BTN_ORDERS = "📦 Заказы"
ADMIN_BTN_CLIENTS = "👤 Клиенты"
ADMIN_BTN_BANNER = "🖼 Добавить/Изменить баннер"
ADMIN_BTN_CANCEL = "❌ Отмена"
ADMIN_BTN_BACK = "⬅️ Назад"


ADMIN_KB = get_keyboard(
    ADMIN_BTN_ADD_ITEM,
    ADMIN_BTN_CATALOG,
    ADMIN_BTN_ORDERS,
    ADMIN_BTN_CLIENTS,
    ADMIN_BTN_BANNER,
    placeholder="\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0434\u0435\u0439\u0441\u0442\u0432\u0438\u0435",
    sizes=(2, 2, 1),
)


def format_price(value: float | None) -> str:
    if value is None or float(value) == 0:
        return "\u0443\u0442\u043e\u0447\u043d\u044f\u0435\u0442\u0441\u044f"
    return f"{round(float(value), 2)} \u0440\u0443\u0431."


def get_banner_pages_markup(page_names: list[str]):
    return get_callback_btns(
        btns={page_name: f"bannerpage_{page_name}" for page_name in page_names},
        sizes=(2,),
    )


def build_admin_order_reply_markup(order, user):
    return get_admin_order_detail_btns(
        order.id,
        user_telegram_id=user.user_id if user else None,
        user_db_id=user.id if user else None,
    )


def build_admin_order_text(order, user) -> str:
    username = f"@{user.username}" if user and user.username else "\u043d\u0435 \u0443\u043a\u0430\u0437\u0430\u043d"
    telegram_id = user.user_id if user else order.user_id
    return (
        f"Username: {escape(username)}\n"
        f"Telegram ID: {telegram_id}\n"
        f"{format_admin_order(order)}"
    )


def format_admin_order(order) -> str:
    status = ORDER_STATUS_LABELS.get(order.status, order.status)
    comment = order.comment or "\u043d\u0435\u0442"
    source_url = f"\u0421\u0441\u044b\u043b\u043a\u0430: {escape(order.source_url)}\n" if order.source_url else ""
    pickup = escape(order.nearest_pickup_point or "\u043d\u0435 \u0432\u044b\u0431\u0440\u0430\u043d")
    batch_code = escape(order.batch_code or "\u043d\u0435\u0442")
    return (
        f"\u0417\u0430\u043a\u0430\u0437 #{order.id}\n"
        f"\u041f\u0430\u043a\u0435\u0442: {batch_code}\n"
        f"\u0422\u043e\u0432\u0430\u0440: {escape(order.product_name)}\n"
        f"{source_url}"
        f"\u0420\u0430\u0437\u043c\u0435\u0440: {escape(order.size)}\n"
        f"\u0422\u0435\u043b\u0435\u0444\u043e\u043d: {escape(order.phone)}\n"
        f"\u0410\u0434\u0440\u0435\u0441: {escape(order.delivery_address or '\u043d\u0435 \u0443\u043a\u0430\u0437\u0430\u043d')}\n"
        f"\u041f\u0412\u0417/\u043f\u043e\u0441\u0442\u0430\u043c\u0430\u0442: {pickup}\n"
        f"\u0421\u0443\u043c\u043c\u0430 \u0442\u043e\u0432\u0430\u0440\u0430: {format_price(order.price)}\n"
        f"\u041a\u043e\u043c\u0438\u0441\u0441\u0438\u044f: {format_price(order.service_fee)}\n"
        f"\u0414\u043e\u0441\u0442\u0430\u0432\u043a\u0430: {format_price(order.delivery_fee)}\n"
        f"\u0418\u0442\u043e\u0433: {format_price(order.total_price)}\n"
        f"\u0421\u0442\u0430\u0442\u0443\u0441: {escape(status)}\n"
        f"\u041a\u043e\u043c\u043c\u0435\u043d\u0442\u0430\u0440\u0438\u0439: {escape(comment)}"
    )


def format_admin_orders_list(orders: list) -> str:
    if not orders:
        return "\u041e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u043d\u044b\u0445 \u0437\u0430\u043a\u0430\u0437\u043e\u0432 \u043f\u043e\u043a\u0430 \u043d\u0435\u0442."

    lines = ["\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0437\u0430\u043a\u0430\u0437 \u043a\u043d\u043e\u043f\u043a\u043e\u0439 \u043d\u0438\u0436\u0435:"]
    for order in orders[:20]:
        lines.append(f"#{order.id} {get_order_status_emoji(order.status)} {escape(order.product_name)}")
    return "\n".join(lines)


def format_client_profile(profile: dict) -> str:
    user = profile["user"]
    orders = profile["orders"]
    addresses = profile["addresses"]
    totals = summarize_order_totals(orders)

    lines = [
        f"\u041a\u043b\u0438\u0435\u043d\u0442: {escape(' '.join(part for part in [user.first_name, user.last_name] if part) or str(user.user_id))}",
        f"Username: {escape('@' + user.username) if user.username else '\u043d\u0435 \u0443\u043a\u0430\u0437\u0430\u043d'}",
        f"Telegram ID: {user.user_id}",
        f"\u0422\u0435\u043b\u0435\u0444\u043e\u043d: {escape(user.phone or '\u043d\u0435 \u0443\u043a\u0430\u0437\u0430\u043d')}",
        f"\u041e\u0441\u043d\u043e\u0432\u043d\u043e\u0439 \u0430\u0434\u0440\u0435\u0441: {escape(user.default_delivery_address or '\u043d\u0435 \u0443\u043a\u0430\u0437\u0430\u043d')}",
        f"\u041e\u0441\u043d\u043e\u0432\u043d\u043e\u0439 \u041f\u0412\u0417: {escape(user.default_pickup_point or '\u043d\u0435 \u0432\u044b\u0431\u0440\u0430\u043d')}",
        f"\u0412\u0441\u0435\u0433\u043e \u0437\u0430\u043a\u0430\u0437\u043e\u0432: {len(orders)}",
        f"\u0421\u0443\u043c\u043c\u0430 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u043d\u044b\u0445 \u0440\u0430\u0441\u0447\u0435\u0442\u043e\u0432: {format_price(totals['total_price'])}",
    ]

    if addresses:
        lines.append("")
        lines.append("\u0421\u043e\u0445\u0440\u0430\u043d\u0435\u043d\u043d\u044b\u0435 \u0430\u0434\u0440\u0435\u0441\u0430:")
        for address in addresses:
            prefix = "\u2605 " if address.is_default else ""
            pickup = f" | {address.pickup_point}" if address.pickup_point else ""
            lines.append(f"{prefix}{escape(address.address)}{escape(pickup)}")

    if orders:
        lines.append("")
        lines.append("\u041f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0435 \u0437\u0430\u043a\u0430\u0437\u044b:")
        for order in orders[:5]:
            status = ORDER_STATUS_LABELS.get(order.status, order.status)
            lines.append(
                f"#{order.id} {escape(order.product_name)} | "
                f"{format_price(order.total_price)} | {escape(status)}"
            )

    return "\n".join(lines)


@admin_router.message(Command("admin"))
async def admin_features(message: types.Message):
    await message.answer("\u0427\u0442\u043e \u0445\u043e\u0442\u0438\u0442\u0435 \u0441\u0434\u0435\u043b\u0430\u0442\u044c?", reply_markup=ADMIN_KB)


@admin_router.message(Command("orders"))
@admin_router.message(F.text == ADMIN_BTN_ORDERS)
async def show_orders(message: types.Message, session: AsyncSession):
    orders = await orm_get_orders(session)
    if not orders:
        await message.answer("\u041e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u043d\u044b\u0445 \u0437\u0430\u043a\u0430\u0437\u043e\u0432 \u043f\u043e\u043a\u0430 \u043d\u0435\u0442.")
        return

    await message.answer(
        format_admin_orders_list(orders),
        reply_markup=get_admin_order_list_btns(orders),
    )


@admin_router.callback_query(F.data == "adminorders_list")
async def admin_orders_list(callback: types.CallbackQuery, session: AsyncSession):
    orders = await orm_get_orders(session)
    if not orders:
        await callback.message.edit_text("\u041e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u043d\u044b\u0445 \u0437\u0430\u043a\u0430\u0437\u043e\u0432 \u043f\u043e\u043a\u0430 \u043d\u0435\u0442.")
        await callback.answer()
        return

    await callback.message.edit_text(
        format_admin_orders_list(orders),
        reply_markup=get_admin_order_list_btns(orders),
    )
    await callback.answer()


@admin_router.callback_query(F.data.startswith("adminorder_"))
async def admin_order_detail(callback: types.CallbackQuery, session: AsyncSession):
    order_id = int(callback.data.split("_")[-1])
    order = await orm_get_order(session, order_id)
    if order is None:
        await callback.answer("\u0417\u0430\u043a\u0430\u0437 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d", show_alert=True)
        return

    user = await orm_get_user_by_db_id(session, order.user_id)
    await callback.message.edit_text(
        build_admin_order_text(order, user),
        reply_markup=build_admin_order_reply_markup(order, user),
    )
    await callback.answer()


@admin_router.message(F.text == ADMIN_BTN_CLIENTS)
async def show_clients(message: types.Message, session: AsyncSession):
    clients = await orm_get_clients(session)
    if not clients:
        await message.answer("\u041a\u0430\u0440\u0442\u043e\u0447\u0435\u043a \u043a\u043b\u0438\u0435\u043d\u0442\u043e\u0432 \u043f\u043e\u043a\u0430 \u043d\u0435\u0442.")
        return

    await message.answer(
        "\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u043a\u043b\u0438\u0435\u043d\u0442\u0430:",
        reply_markup=get_client_list_btns(clients),
    )


@admin_router.callback_query(F.data.startswith("client_"))
async def show_client_profile(callback: types.CallbackQuery, session: AsyncSession):
    user_db_id = int(callback.data.split("_")[-1])
    profile = await orm_get_client_profile(session, user_db_id)
    if profile is None:
        await callback.answer("\u041a\u043b\u0438\u0435\u043d\u0442 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d", show_alert=True)
        return

    await callback.message.answer(format_client_profile(profile))
    await callback.answer()


@admin_router.callback_query(F.data.startswith("adminmessage_"))
async def admin_message_start(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    order_id = int(callback.data.split("_")[-1])
    order = await orm_get_order(session, order_id)
    if order is None:
        await callback.answer("\u0417\u0430\u043a\u0430\u0437 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d", show_alert=True)
        return

    user = await orm_get_user_by_db_id(session, order.user_id)
    if user is None:
        await callback.answer("\u041a\u043b\u0438\u0435\u043d\u0442 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d", show_alert=True)
        return

    await state.set_state(AdminMessageToClient.text)
    await state.update_data(order_id=order.id, user_telegram_id=user.user_id)
    await callback.message.answer(
        f"\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435 \u0434\u043b\u044f \u043a\u043b\u0438\u0435\u043d\u0442\u0430 \u043f\u043e \u0437\u0430\u043a\u0430\u0437\u0443 #{order.id}.",
        reply_markup=get_keyboard(ADMIN_BTN_CANCEL, sizes=(1,)),
    )
    await callback.answer()


@admin_router.message(AdminMessageToClient.text, F.text)
async def admin_message_send(message: types.Message, state: FSMContext):
    text = message.text.strip()
    if text == ADMIN_BTN_CANCEL or text.casefold() == "\u043e\u0442\u043c\u0435\u043d\u0430":
        await state.clear()
        await message.answer(
            "\u041e\u0442\u043f\u0440\u0430\u0432\u043a\u0430 \u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u044f \u043e\u0442\u043c\u0435\u043d\u0435\u043d\u0430.",
            reply_markup=ADMIN_KB,
        )
        return

    data = await state.get_data()
    user_telegram_id = data.get("user_telegram_id")
    order_id = data.get("order_id")
    if not user_telegram_id:
        await state.clear()
        await message.answer(
            "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043e\u043f\u0440\u0435\u0434\u0435\u043b\u0438\u0442\u044c \u043a\u043b\u0438\u0435\u043d\u0442\u0430.",
            reply_markup=ADMIN_KB,
        )
        return

    try:
        await message.bot.send_message(
            user_telegram_id,
            f"\u0421\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435 \u043e\u0442 \u0430\u0434\u043c\u0438\u043d\u0438\u0441\u0442\u0440\u0430\u0442\u043e\u0440\u0430 \u043f\u043e \u0437\u0430\u043a\u0430\u0437\u0443 #{order_id}:\n\n{text}",
        )
    except Exception:
        await state.clear()
        await message.answer(
            "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043e\u0442\u043f\u0440\u0430\u0432\u0438\u0442\u044c \u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435 \u043a\u043b\u0438\u0435\u043d\u0442\u0443.",
            reply_markup=ADMIN_KB,
        )
        return

    await state.clear()
    await message.answer(
        "\u0421\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435 \u043e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u043e.",
        reply_markup=ADMIN_KB,
    )


@admin_router.callback_query(F.data.startswith("orderstatus_"))
async def change_order_status(callback: types.CallbackQuery, session: AsyncSession):
    _, order_id, status = callback.data.split("_", 2)
    order_id_int = int(order_id)

    await orm_update_order_status(session, order_id_int, status)
    order = await orm_get_order(session, order_id_int)
    user = await orm_get_user_by_db_id(session, order.user_id)
    await callback.message.edit_text(
        build_admin_order_text(order, user),
        reply_markup=build_admin_order_reply_markup(order, user),
    )

    if user is not None:
        try:
            status_label = ORDER_STATUS_LABELS.get(status, status)
            notification_text = (
                f"\u041e\u0431\u043d\u043e\u0432\u043b\u0435\u043d\u0438\u0435 \u043f\u043e \u0437\u0430\u043a\u0430\u0437\u0443 #{order.id}\n"
                f"\u0422\u043e\u0432\u0430\u0440: {order.product_name}\n"
                f"\u041d\u043e\u0432\u044b\u0439 \u0441\u0442\u0430\u0442\u0443\u0441: {status_label}\n"
                f"\u0418\u0442\u043e\u0433: {format_price(order.total_price)}"
            )
            if status == "confirmed":
                notification_text += "\n\u0417\u0430\u044f\u0432\u043a\u0430 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u0430 \u0430\u0434\u043c\u0438\u043d\u0438\u0441\u0442\u0440\u0430\u0442\u043e\u0440\u043e\u043c."
            await callback.bot.send_message(user.user_id, notification_text)
        except Exception:
            pass

    await callback.answer("\u0421\u0442\u0430\u0442\u0443\u0441 \u043e\u0431\u043d\u043e\u0432\u043b\u0435\u043d")


@admin_router.callback_query(F.data.startswith("admindelete_"))
async def admin_delete_order(callback: types.CallbackQuery, session: AsyncSession):
    order_id = int(callback.data.split("_")[-1])
    deleted = await orm_delete_order(session, order_id)
    if not deleted:
        await callback.answer("\u0417\u0430\u043a\u0430\u0437 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d", show_alert=True)
        return

    orders = await orm_get_orders(session)
    if not orders:
        await callback.message.edit_text("\u041e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u043d\u044b\u0445 \u0437\u0430\u043a\u0430\u0437\u043e\u0432 \u043f\u043e\u043a\u0430 \u043d\u0435\u0442.")
    else:
        await callback.message.edit_text(
            format_admin_orders_list(orders),
            reply_markup=get_admin_order_list_btns(orders),
        )
    await callback.answer("\u0417\u0430\u043a\u0430\u0437 \u0443\u0434\u0430\u043b\u0435\u043d")


@admin_router.message(F.text == ADMIN_BTN_CATALOG)
async def show_catalog(message: types.Message, session: AsyncSession):
    categories = await orm_get_categories(session)
    btns = {category.name: f"category_{category.id}" for category in categories}
    await message.answer("\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u043a\u0430\u0442\u0435\u0433\u043e\u0440\u0438\u044e", reply_markup=get_callback_btns(btns=btns))


@admin_router.callback_query(F.data.startswith("category_"))
async def show_items(callback: types.CallbackQuery, session: AsyncSession):
    category_id = int(callback.data.split("_")[-1])
    items = await orm_get_items(session, category_id)
    if not items:
        await callback.message.answer("\u0412 \u044d\u0442\u043e\u0439 \u043a\u0430\u0442\u0435\u0433\u043e\u0440\u0438\u0438 \u043f\u043e\u043a\u0430 \u043d\u0435\u0442 \u0442\u043e\u0432\u0430\u0440\u043e\u0432.")
        await callback.answer()
        return

    for item in items:
        await callback.message.answer_photo(
            item.image,
            caption=(
                f"<strong>{escape(item.name)}</strong>\n"
                f"{escape(item.size)}\n"
                f"\u0421\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u044c: {round(float(item.price), 2)} \u0440\u0443\u0431."
            ),
            reply_markup=get_callback_btns(
                btns={
                    "\u0423\u0434\u0430\u043b\u0438\u0442\u044c": f"delete_{item.id}",
                    "\u0418\u0437\u043c\u0435\u043d\u0438\u0442\u044c": f"change_{item.id}",
                },
                sizes=(2,),
            ),
        )
    await callback.answer()


@admin_router.callback_query(F.data.startswith("delete_"))
async def delete_item(callback: types.CallbackQuery, session: AsyncSession):
    item_id = int(callback.data.split("_")[-1])
    await orm_delete_item(session, item_id)
    await callback.answer("\u0422\u043e\u0432\u0430\u0440 \u0443\u0434\u0430\u043b\u0435\u043d")
    await callback.message.answer("\u0422\u043e\u0432\u0430\u0440 \u0443\u0434\u0430\u043b\u0435\u043d.")


class AddBanner(StatesGroup):
    page = State()
    image = State()


@admin_router.message(StateFilter(None), F.text == ADMIN_BTN_BANNER)
async def add_banner_prompt(message: types.Message, state: FSMContext):
    pages_names = list(description_for_info_pages.keys())
    await message.answer(
        "\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0441\u0442\u0440\u0430\u043d\u0438\u0446\u0443, \u0434\u043b\u044f \u043a\u043e\u0442\u043e\u0440\u043e\u0439 \u043d\u0443\u0436\u043d\u043e \u043e\u0431\u043d\u043e\u0432\u0438\u0442\u044c \u0431\u0430\u043d\u043d\u0435\u0440.",
        reply_markup=get_banner_pages_markup(pages_names),
    )
    await state.set_state(AddBanner.page)


@admin_router.callback_query(AddBanner.page, F.data.startswith("bannerpage_"))
async def add_banner_choose_page(callback: types.CallbackQuery, state: FSMContext):
    page_name = callback.data.split("_", 1)[1]
    await state.update_data(page_name=page_name)
    await state.set_state(AddBanner.image)
    await callback.message.answer(f"\u041e\u0442\u043f\u0440\u0430\u0432\u044c\u0442\u0435 \u0444\u043e\u0442\u043e \u0434\u043b\u044f \u0441\u0442\u0440\u0430\u043d\u0438\u0446\u044b '{page_name}'.")
    await callback.answer()


@admin_router.message(AddBanner.image, F.photo)
async def add_banner(message: types.Message, state: FSMContext, session: AsyncSession):
    image_id = message.photo[-1].file_id
    data = await state.get_data()
    page_name = data.get("page_name")

    if not page_name:
        await message.answer("\u0421\u043d\u0430\u0447\u0430\u043b\u0430 \u0432\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0441\u0442\u0440\u0430\u043d\u0438\u0446\u0443 \u0434\u043b\u044f \u0431\u0430\u043d\u043d\u0435\u0440\u0430.")
        return

    await orm_change_banner_image(session, page_name, image_id)
    await message.answer("\u0411\u0430\u043d\u043d\u0435\u0440 \u043e\u0431\u043d\u043e\u0432\u043b\u0435\u043d.", reply_markup=ADMIN_KB)
    await state.clear()


@admin_router.message(AddBanner.page)
async def invalid_banner_page(message: types.Message):
    pages_names = list(description_for_info_pages.keys())
    await message.answer(
        "\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0441\u0442\u0440\u0430\u043d\u0438\u0446\u0443 \u043a\u043d\u043e\u043f\u043a\u043e\u0439 \u043d\u0438\u0436\u0435.",
        reply_markup=get_banner_pages_markup(pages_names),
    )


@admin_router.message(AddBanner.image)
async def invalid_banner_input(message: types.Message):
    await message.answer("\u041e\u0442\u043f\u0440\u0430\u0432\u044c\u0442\u0435 \u0444\u043e\u0442\u043e \u0431\u0430\u043d\u043d\u0435\u0440\u0430.")


class AddProduct(StatesGroup):
    name = State()
    size = State()
    category = State()
    price = State()
    image = State()

    item_for_change = None
    texts = {
        "AddProduct:name": "\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u043d\u0430\u0437\u0432\u0430\u043d\u0438\u0435 \u0437\u0430\u043d\u043e\u0432\u043e:",
        "AddProduct:size": "\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u0440\u0430\u0437\u043c\u0435\u0440\u044b \u0437\u0430\u043d\u043e\u0432\u043e:",
        "AddProduct:category": "\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u043a\u0430\u0442\u0435\u0433\u043e\u0440\u0438\u044e \u0437\u0430\u043d\u043e\u0432\u043e:",
        "AddProduct:price": "\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u044c \u0437\u0430\u043d\u043e\u0432\u043e:",
        "AddProduct:image": "\u0417\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u0435 \u0438\u0437\u043e\u0431\u0440\u0430\u0436\u0435\u043d\u0438\u0435 \u0437\u0430\u043d\u043e\u0432\u043e:",
    }


@admin_router.callback_query(StateFilter(None), F.data.startswith("change_"))
async def change_product_callback(
    callback: types.CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
):
    item_id = int(callback.data.split("_")[-1])
    AddProduct.item_for_change = await orm_get_item(session, item_id)
    await callback.answer()
    await callback.message.answer(
        "\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u043d\u0430\u0437\u0432\u0430\u043d\u0438\u0435 \u0442\u043e\u0432\u0430\u0440\u0430",
        reply_markup=types.ReplyKeyboardRemove(),
    )
    await state.set_state(AddProduct.name)


@admin_router.message(StateFilter(None), F.text == ADMIN_BTN_ADD_ITEM)
async def add_item(message: types.Message, state: FSMContext):
    await message.answer(
        "\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u043d\u0430\u0437\u0432\u0430\u043d\u0438\u0435 \u0442\u043e\u0432\u0430\u0440\u0430",
        reply_markup=types.ReplyKeyboardRemove(),
    )
    await state.set_state(AddProduct.name)


@admin_router.message(StateFilter("*"), Command("\u043e\u0442\u043c\u0435\u043d\u0430"))
@admin_router.message(StateFilter("*"), or_f(F.text.casefold() == "\u043e\u0442\u043c\u0435\u043d\u0430", F.text == ADMIN_BTN_CANCEL))
async def cancel_handler(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        return

    AddProduct.item_for_change = None
    await state.clear()
    await message.answer("\u0414\u0435\u0439\u0441\u0442\u0432\u0438\u044f \u043e\u0442\u043c\u0435\u043d\u0435\u043d\u044b", reply_markup=ADMIN_KB)


@admin_router.message(StateFilter("*"), Command("\u043d\u0430\u0437\u0430\u0434"))
@admin_router.message(StateFilter("*"), or_f(F.text.casefold() == "\u043d\u0430\u0437\u0430\u0434", F.text == ADMIN_BTN_BACK))
async def back_step_handler(message: types.Message, state: FSMContext):
    current_state = await state.get_state()

    if current_state == AddProduct.name.state:
        await message.answer(
            '\u041f\u0440\u0435\u0434\u044b\u0434\u0443\u0449\u0435\u0433\u043e \u0448\u0430\u0433\u0430 \u043d\u0435\u0442. '
            '\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u043d\u0430\u0437\u0432\u0430\u043d\u0438\u0435 \u0442\u043e\u0432\u0430\u0440\u0430 \u0438\u043b\u0438 "\u043e\u0442\u043c\u0435\u043d\u0430".'
        )
        return

    previous = None
    for step in AddProduct.__all_states__:
        if step.state == current_state and previous is not None:
            await state.set_state(previous)
            await message.answer(
                f"\u0412\u043e\u0437\u0432\u0440\u0430\u0442 \u043a \u043f\u0440\u0435\u0434\u044b\u0434\u0443\u0449\u0435\u043c\u0443 \u0448\u0430\u0433\u0443.\n{AddProduct.texts[previous.state]}"
            )
            return
        previous = step


@admin_router.message(AddProduct.name, F.text)
async def add_name(message: types.Message, state: FSMContext):
    if message.text == "." and AddProduct.item_for_change:
        await state.update_data(name=AddProduct.item_for_change.name)
    else:
        if not 3 <= len(message.text.strip()) <= 150:
            await message.answer(
                "\u041d\u0430\u0437\u0432\u0430\u043d\u0438\u0435 \u0442\u043e\u0432\u0430\u0440\u0430 \u0434\u043e\u043b\u0436\u043d\u043e \u0431\u044b\u0442\u044c \u043e\u0442 3 \u0434\u043e 150 \u0441\u0438\u043c\u0432\u043e\u043b\u043e\u0432. "
                "\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u0437\u0430\u043d\u043e\u0432\u043e."
            )
            return
        await state.update_data(name=message.text.strip())

    await message.answer("\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u0440\u0430\u0437\u043c\u0435\u0440\u044b \u0442\u043e\u0432\u0430\u0440\u0430")
    await state.set_state(AddProduct.size)


@admin_router.message(AddProduct.name)
async def invalid_name(message: types.Message):
    await message.answer("\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u0442\u0435\u043a\u0441\u0442\u043e\u0432\u043e\u0435 \u043d\u0430\u0437\u0432\u0430\u043d\u0438\u0435 \u0442\u043e\u0432\u0430\u0440\u0430.")


@admin_router.message(AddProduct.size, F.text)
async def add_size(message: types.Message, state: FSMContext, session: AsyncSession):
    if message.text == "." and AddProduct.item_for_change:
        await state.update_data(size=AddProduct.item_for_change.size)
    else:
        if len(message.text.strip()) < 2:
            await message.answer(
                "\u0421\u043b\u0438\u0448\u043a\u043e\u043c \u043a\u043e\u0440\u043e\u0442\u043a\u043e\u0435 \u043e\u043f\u0438\u0441\u0430\u043d\u0438\u0435 \u0440\u0430\u0437\u043c\u0435\u0440\u043e\u0432. "
                "\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u0437\u0430\u043d\u043e\u0432\u043e."
            )
            return
        await state.update_data(size=message.text.strip())

    categories = await orm_get_categories(session)
    btns = {category.name: str(category.id) for category in categories}
    await message.answer("\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u043a\u0430\u0442\u0435\u0433\u043e\u0440\u0438\u044e", reply_markup=get_callback_btns(btns=btns))
    await state.set_state(AddProduct.category)


@admin_router.message(AddProduct.size)
async def invalid_size(message: types.Message):
    await message.answer("\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u0442\u0435\u043a\u0441\u0442\u043e\u0432\u043e\u0435 \u043e\u043f\u0438\u0441\u0430\u043d\u0438\u0435 \u0440\u0430\u0437\u043c\u0435\u0440\u043e\u0432.")


@admin_router.callback_query(AddProduct.category)
async def category_choice(
    callback: types.CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
):
    category_ids = [category.id for category in await orm_get_categories(session)]
    if not callback.data.isdigit() or int(callback.data) not in category_ids:
        await callback.message.answer("\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u043a\u0430\u0442\u0435\u0433\u043e\u0440\u0438\u044e \u0438\u0437 \u043a\u043d\u043e\u043f\u043e\u043a.")
        await callback.answer()
        return

    await callback.answer()
    await state.update_data(category=callback.data)
    await callback.message.answer("\u0422\u0435\u043f\u0435\u0440\u044c \u0432\u0432\u0435\u0434\u0438\u0442\u0435 \u0446\u0435\u043d\u0443 \u0442\u043e\u0432\u0430\u0440\u0430.")
    await state.set_state(AddProduct.price)


@admin_router.message(AddProduct.category)
async def invalid_category(message: types.Message):
    await message.answer("\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u043a\u0430\u0442\u0435\u0433\u043e\u0440\u0438\u044e \u0438\u0437 \u043a\u043d\u043e\u043f\u043e\u043a.")


@admin_router.message(AddProduct.price, F.text)
async def add_price(message: types.Message, state: FSMContext):
    if message.text == "." and AddProduct.item_for_change:
        await state.update_data(price=AddProduct.item_for_change.price)
    else:
        try:
            float(message.text)
        except ValueError:
            await message.answer("\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u043a\u043e\u0440\u0440\u0435\u043a\u0442\u043d\u043e\u0435 \u0437\u043d\u0430\u0447\u0435\u043d\u0438\u0435 \u0446\u0435\u043d\u044b.")
            return

        await state.update_data(price=message.text)

    await message.answer("\u0417\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u0435 \u0438\u0437\u043e\u0431\u0440\u0430\u0436\u0435\u043d\u0438\u0435 \u0442\u043e\u0432\u0430\u0440\u0430.")
    await state.set_state(AddProduct.image)


@admin_router.message(AddProduct.price)
async def invalid_price(message: types.Message):
    await message.answer("\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u044c \u0442\u043e\u0432\u0430\u0440\u0430.")


@admin_router.message(AddProduct.image, or_f(F.photo, F.text == "."))
async def add_image(message: types.Message, state: FSMContext, session: AsyncSession):
    if message.text == "." and AddProduct.item_for_change:
        await state.update_data(image=AddProduct.item_for_change.image)
    elif message.photo:
        await state.update_data(image=message.photo[-1].file_id)
    else:
        await message.answer("\u041e\u0442\u043f\u0440\u0430\u0432\u044c\u0442\u0435 \u0444\u043e\u0442\u043e \u0442\u043e\u0432\u0430\u0440\u0430.")
        return

    data = await state.get_data()
    try:
        if AddProduct.item_for_change:
            await orm_update_item(session, AddProduct.item_for_change.id, data)
        else:
            await orm_add_item(session, data)
        await message.answer("\u0422\u043e\u0432\u0430\u0440 \u0434\u043e\u0431\u0430\u0432\u043b\u0435\u043d \u0438\u043b\u0438 \u0438\u0437\u043c\u0435\u043d\u0435\u043d.", reply_markup=ADMIN_KB)
    except Exception as exc:
        await message.answer(f"\u041e\u0448\u0438\u0431\u043a\u0430:\n{exc}", reply_markup=ADMIN_KB)
    finally:
        AddProduct.item_for_change = None
        await state.clear()


@admin_router.message(AddProduct.image)
async def invalid_image(message: types.Message):
    await message.answer("\u041e\u0442\u043f\u0440\u0430\u0432\u044c\u0442\u0435 \u0444\u043e\u0442\u043e \u0442\u043e\u0432\u0430\u0440\u0430.")
