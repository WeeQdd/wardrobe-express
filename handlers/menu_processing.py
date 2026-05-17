from html import escape

from aiogram.types import InputMediaPhoto
from sqlalchemy.ext.asyncio import AsyncSession

from database.orm_query import (
    Paginator,
    orm_get_banner,
    orm_get_categories,
    orm_get_items,
    orm_get_user,
    orm_get_user_active_batch_orders,
    orm_get_user_orders,
    orm_get_user_saved_addresses,
)
from kbds.inline import (
    get_items_btns,
    get_order_status_emoji,
    get_user_catalog_btns,
    get_user_info_btns,
    get_user_main_btns,
    get_user_order_btns,
    get_user_order_list_btns,
    get_user_orders_btns,
    get_user_profile_btns,
)
from services.pricing import summarize_order_totals


def format_price(value: float | None) -> str:
    if value is None or float(value) == 0:
        return "уточняется"
    return f"{round(float(value), 2)} руб."


async def build_banner_media(session: AsyncSession, page_name: str, caption: str):
    banner = await orm_get_banner(session, page_name)
    media = banner.image if banner and banner.image else None

    if not media:
        main_banner = await orm_get_banner(session, "main")
        media = main_banner.image if main_banner else None

    return InputMediaPhoto(media=media, caption=caption)


async def main_menu(session: AsyncSession, level: int, menu_name: str):
    banner = await orm_get_banner(session, menu_name)
    image = await build_banner_media(session, menu_name, banner.description)
    kbds = get_user_main_btns(level=level)
    return image, kbds


async def info_page(session: AsyncSession, menu_name: str):
    banner = await orm_get_banner(session, menu_name)
    image = await build_banner_media(session, menu_name, banner.description)
    kbds = get_user_info_btns()
    return image, kbds


async def catalog(session: AsyncSession, level: int, menu_name: str):
    banner = await orm_get_banner(session, menu_name)
    image = await build_banner_media(session, menu_name, banner.description)
    categories = await orm_get_categories(session)
    kbds = get_user_catalog_btns(level=level, categories=categories)
    return image, kbds


def pages(paginator: Paginator) -> dict[str, int]:
    btns = {}
    if paginator.has_previous():
        btns["◀ Пред."] = paginator.has_previous()
    if paginator.has_next():
        btns["След. ▶"] = paginator.has_next()
    return btns


async def items(session: AsyncSession, level: int, category: int, page: int):
    all_items = await orm_get_items(session, category_id=category)
    paginator = Paginator(all_items, page=page)
    current_page = paginator.get_page()

    if not current_page:
        return None

    item = current_page[0]
    image = InputMediaPhoto(
        media=item.image,
        caption=(
            f"<strong>{escape(item.name)}</strong>\n"
            f"Размеры: {escape(item.size)}\n"
            f"Цена товара: {round(float(item.price), 2)} руб.\n"
            f"<strong>Товар {paginator.page}/{paginator.pages}</strong>"
        ),
    )

    kbds = get_items_btns(
        level=level,
        category=category,
        page=page,
        pagination_btns=pages(paginator),
        item_id=item.id,
    )
    return image, kbds


def format_active_batch(orders: list) -> str | None:
    if not orders:
        return None

    totals = summarize_order_totals(orders)
    first = orders[0]
    lines = ["Текущая заявка:", ""]
    for index, order in enumerate(orders, start=1):
        lines.append(
            f"{index}. {escape(order.product_name)} | размер: {escape(order.size)} | "
            f"итого: {format_price(order.total_price)}"
        )

    lines.extend(
        [
            "",
            f"Телефон: {escape(first.phone)}",
            f"Адрес: {escape(first.delivery_address or 'не указан')}",
            f"ПВЗ/постамат: {escape(first.nearest_pickup_point or 'не выбран')}",
            f"Сумма товаров: {format_price(totals['subtotal'])}",
            f"Доставка: {format_price(totals['delivery_fee'])}",
            f"Предварительный итог: {format_price(totals['total_price'])}",
        ]
    )
    if totals["unknown_count"]:
        lines.append(f"Позиции с неуточненной ценой: {totals['unknown_count']}")

    return "\n".join(lines)


def format_orders(active_batch_orders: list, orders: list) -> str:
    blocks: list[str] = []

    active_batch_text = format_active_batch(active_batch_orders)
    if active_batch_text:
        blocks.append(active_batch_text)

    if not orders:
        blocks.append("История отправленных заявок пока пуста.")
        return "\n\n".join(blocks)

    lines = ["Выберите заявку кнопкой ниже:"]
    for order in orders[:10]:
        lines.append(f"#{order.id} {get_order_status_emoji(order.status)} {escape(order.product_name)}")

    blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


async def user_orders(session: AsyncSession, telegram_user_id: int):
    orders = await orm_get_user_orders(session, telegram_user_id)
    active_batch_orders = await orm_get_user_active_batch_orders(session, telegram_user_id)
    image = await build_banner_media(session, "myorders", format_orders(active_batch_orders, orders))
    if orders:
        kbds = get_user_order_list_btns(orders, has_active_batch=bool(active_batch_orders))
    else:
        kbds = get_user_orders_btns(has_active_batch=bool(active_batch_orders))
    return image, kbds


async def user_profile(session: AsyncSession, telegram_user_id: int):
    user = await orm_get_user(session, telegram_user_id)
    saved_addresses = await orm_get_user_saved_addresses(session, telegram_user_id, limit=5)
    orders = await orm_get_user_orders(session, telegram_user_id)
    active_batch_orders = await orm_get_user_active_batch_orders(session, telegram_user_id)

    lines = [
        "Профиль клиента",
        "",
        f"Телефон: {escape(user.phone or 'не указан') if user else 'не указан'}",
        f"Основной адрес: {escape(user.default_delivery_address or 'не указан') if user else 'не указан'}",
        f"Основной ПВЗ: {escape(user.default_pickup_point or 'не выбран') if user else 'не выбран'}",
        f"Отправленных заказов: {len(orders)}",
        f"Текущих позиций в заявке: {len(active_batch_orders)}",
    ]

    if saved_addresses:
        lines.extend(["", "Сохраненные адреса:"])
        for address in saved_addresses:
            prefix = "★ " if address.is_default else ""
            pickup = f" | {address.pickup_point}" if address.pickup_point else ""
            lines.append(f"{prefix}{escape(address.address)}{escape(pickup)}")

    image = await build_banner_media(session, "profile", "\n".join(lines))
    kbds = get_user_profile_btns()
    return image, kbds


async def order_page(session: AsyncSession):
    banner = await orm_get_banner(session, "order")
    image = await build_banner_media(session, "order", banner.description)
    kbds = get_user_order_btns()
    return image, kbds


async def get_menu_content(
    session: AsyncSession,
    level: int,
    menu_name: str,
    category: int | None = None,
    page: int | None = None,
    user_id: int | None = None,
):
    if menu_name == "main":
        return await main_menu(session, level, menu_name)
    if menu_name == "faq":
        return await info_page(session, menu_name)
    if menu_name == "myorders":
        return await user_orders(session, user_id)
    if menu_name == "profile":
        return await user_profile(session, user_id)
    if menu_name == "order":
        return await order_page(session)
    if menu_name == "in_stock":
        return await catalog(session, level, menu_name)
    if level == 2 and category is not None:
        return await items(session, level, category, page or 1)

    return await main_menu(session, 0, "main")
