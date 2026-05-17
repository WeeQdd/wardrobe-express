from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


class MenuCallBack(CallbackData, prefix="menu"):
    level: int
    menu_name: str
    category: int | None = None
    page: int = 1


def get_callback_btns(
    *,
    btns: dict[str, str],
    sizes: tuple[int, ...] = (2,),
) -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardBuilder()

    for text, callback_data in btns.items():
        keyboard.button(text=text, callback_data=callback_data)

    keyboard.adjust(*sizes)
    return keyboard.as_markup()


def get_inline_mix_btns(
    *,
    btns: dict[str, str],
    sizes: tuple[int, ...] = (2,),
) -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardBuilder()

    for text, target in btns.items():
        if target.startswith(("http://", "https://", "tg://")):
            keyboard.button(text=text, url=target)
        else:
            keyboard.button(text=text, callback_data=target)

    keyboard.adjust(*sizes)
    return keyboard.as_markup()


def get_inlineMix_btns(
    *,
    btns: dict[str, str],
    sizes: tuple[int, ...] = (2,),
) -> InlineKeyboardMarkup:
    return get_inline_mix_btns(btns=btns, sizes=sizes)


def get_user_main_btns(level: int) -> InlineKeyboardMarkup:
    return get_inline_mix_btns(
        btns={
            "В наличии": MenuCallBack(level=level + 1, menu_name="in_stock").pack(),
            "Заказ": MenuCallBack(level=level + 1, menu_name="order").pack(),
            "Конвертер": "converter_",
            "Мои заявки": MenuCallBack(level=level + 1, menu_name="myorders").pack(),
            "Профиль": MenuCallBack(level=level + 1, menu_name="profile").pack(),
            "FAQ": MenuCallBack(level=level + 1, menu_name="faq").pack(),
        },
        sizes=(2, 2, 2),
    )


def get_user_info_btns() -> InlineKeyboardMarkup:
    return get_inline_mix_btns(
        btns={"Меню": MenuCallBack(level=0, menu_name="main").pack()},
        sizes=(1,),
    )


def get_user_orders_btns(*, has_active_batch: bool = False) -> InlineKeyboardMarkup:
    btns = {
        "Новый заказ": MenuCallBack(level=1, menu_name="order").pack(),
        "Профиль": MenuCallBack(level=1, menu_name="profile").pack(),
        "Меню": MenuCallBack(level=0, menu_name="main").pack(),
    }
    if has_active_batch:
        btns = {
            "Текущая заявка": "batch_open",
            **btns,
        }

    return get_inline_mix_btns(btns=btns, sizes=(1, 1, 1, 1))


def get_user_profile_btns() -> InlineKeyboardMarkup:
    return get_inline_mix_btns(
        btns={
            "Новый заказ": MenuCallBack(level=1, menu_name="order").pack(),
            "Мои заявки": MenuCallBack(level=1, menu_name="myorders").pack(),
            "Меню": MenuCallBack(level=0, menu_name="main").pack(),
        },
        sizes=(1, 1, 1),
    )


def get_user_order_btns() -> InlineKeyboardMarkup:
    return get_inline_mix_btns(
        btns={
            "Отправить ссылку": "start_link_order",
            "Меню": MenuCallBack(level=0, menu_name="main").pack(),
        },
        sizes=(1, 1),
    )


def get_user_catalog_btns(level: int, categories: list) -> InlineKeyboardMarkup:
    btns = {
        category.name: MenuCallBack(
            level=level + 1,
            menu_name="in_stock",
            category=category.id,
            page=1,
        ).pack()
        for category in categories
    }
    btns["Назад"] = MenuCallBack(level=0, menu_name="main").pack()
    return get_inline_mix_btns(btns=btns, sizes=(2, 2, 1))


def get_items_btns(
    *,
    level: int,
    category: int,
    page: int,
    pagination_btns: dict[str, int],
    item_id: int,
) -> InlineKeyboardMarkup:
    btns = {
        "Добавить в заявку": f"order_{item_id}",
        **{
            text: MenuCallBack(
                level=level,
                menu_name="in_stock",
                category=category,
                page=target_page,
            ).pack()
            for text, target_page in pagination_btns.items()
        },
        "Назад": MenuCallBack(level=1, menu_name="in_stock").pack(),
    }
    return get_inline_mix_btns(btns=btns, sizes=(1, 2, 1))


def get_batch_actions_btns() -> InlineKeyboardMarkup:
    return get_inline_mix_btns(
        btns={
            "Отправить заявку": "batch_finalize",
            "В наличии": MenuCallBack(level=1, menu_name="in_stock").pack(),
            "Заказ": MenuCallBack(level=1, menu_name="order").pack(),
            "Профиль": MenuCallBack(level=1, menu_name="profile").pack(),
            "Сбросить заявку": "batch_cancel",
        },
        sizes=(1, 2, 1, 1),
    )


def get_saved_profile_btns() -> InlineKeyboardMarkup:
    return get_inline_mix_btns(
        btns={
            "Выбрать сохраненный адрес": "order_use_saved",
            "Указать новые данные": "order_use_new",
        },
        sizes=(1, 1),
    )


def get_saved_addresses_btns(addresses: list) -> InlineKeyboardMarkup:
    btns = {}
    for address in addresses:
        label = address.address
        if len(label) > 32:
            label = f"{label[:29]}..."
        if address.is_default:
            label = f"★ {label}"
        btns[label] = f"saved_address_{address.id}"

    btns["Новый адрес"] = "order_use_new"
    return get_inline_mix_btns(btns=btns, sizes=(1,) * len(btns))


def get_order_status_btns(order_id: int) -> InlineKeyboardMarkup:
    return get_callback_btns(
        btns={
            "Подтвердить": f"orderstatus_{order_id}_confirmed",
            "Ожидает оплату": f"orderstatus_{order_id}_awaiting_payment",
            "Оплачен": f"orderstatus_{order_id}_paid",
            "Выкуплен": f"orderstatus_{order_id}_purchased",
            "На складе": f"orderstatus_{order_id}_at_warehouse",
            "В пути": f"orderstatus_{order_id}_in_transit",
            "Готов к выдаче": f"orderstatus_{order_id}_ready_for_pickup",
            "Выдан": f"orderstatus_{order_id}_done",
            "Отменить": f"orderstatus_{order_id}_cancelled",
        },
        sizes=(2, 2, 2, 2, 1),
    )


def get_client_list_btns(clients: list) -> InlineKeyboardMarkup:
    btns = {}
    for client in clients:
        name = " ".join(part for part in [client.first_name, client.last_name] if part).strip() or str(client.user_id)
        btns[name[:40]] = f"client_{client.id}"

    return get_callback_btns(btns=btns, sizes=(1,) * max(len(btns), 1))


def get_order_status_emoji(status: str) -> str:
    if status in {"done"}:
        return "✅"
    if status in {"cancelled"}:
        return "❌"
    return "⏳"


def get_user_order_list_btns(orders: list, *, has_active_batch: bool = False) -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardBuilder()

    for order in orders[:10]:
        keyboard.button(
            text=f"#{order.id} {get_order_status_emoji(order.status)}",
            callback_data=f"userorder_{order.id}",
        )

    if has_active_batch:
        keyboard.button(text="Текущая заявка", callback_data="batch_open")
    keyboard.button(text="Новый заказ", callback_data=MenuCallBack(level=1, menu_name="order").pack())
    keyboard.button(text="Профиль", callback_data=MenuCallBack(level=1, menu_name="profile").pack())
    keyboard.button(text="Меню", callback_data=MenuCallBack(level=0, menu_name="main").pack())
    keyboard.adjust(2, 2, 1, 1)
    return keyboard.as_markup()


def get_user_order_detail_btns(order_id: int, *, can_cancel: bool) -> InlineKeyboardMarkup:
    btns = {}
    if can_cancel:
        btns["Отменить заявку"] = f"userordercancel_{order_id}"
    btns["Назад к заявкам"] = MenuCallBack(level=1, menu_name="myorders").pack()
    btns["Меню"] = MenuCallBack(level=0, menu_name="main").pack()
    return get_inline_mix_btns(btns=btns, sizes=(1, 1, 1))


def get_admin_order_list_btns(orders: list) -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardBuilder()

    for order in orders[:20]:
        keyboard.button(
            text=f"#{order.id} {get_order_status_emoji(order.status)}",
            callback_data=f"adminorder_{order.id}",
        )

    keyboard.adjust(2)
    return keyboard.as_markup()


def get_admin_order_detail_btns(
    order_id: int,
    *,
    user_telegram_id: int | None = None,
    user_db_id: int | None = None,
) -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardBuilder()

    for text, callback_data in {
        "Подтвердить": f"orderstatus_{order_id}_confirmed",
        "Ожидает оплату": f"orderstatus_{order_id}_awaiting_payment",
        "Оплачен": f"orderstatus_{order_id}_paid",
        "Выкуплен": f"orderstatus_{order_id}_purchased",
        "На складе": f"orderstatus_{order_id}_at_warehouse",
        "В пути": f"orderstatus_{order_id}_in_transit",
        "Готов к выдаче": f"orderstatus_{order_id}_ready_for_pickup",
        "Выдан": f"orderstatus_{order_id}_done",
        "Отменить": f"orderstatus_{order_id}_cancelled",
    }.items():
        keyboard.button(text=text, callback_data=callback_data)

    if user_telegram_id:
        keyboard.button(text="Написать клиенту", callback_data=f"adminmessage_{order_id}")
    if user_db_id:
        keyboard.button(text="Карточка клиента", callback_data=f"client_{user_db_id}")
    keyboard.button(text="Удалить заказ", callback_data=f"admindelete_{order_id}")
    keyboard.button(text="Назад к списку", callback_data="adminorders_list")

    rows = [2, 2, 2, 2]
    if user_telegram_id:
        rows.append(1)
    if user_db_id:
        rows.append(1)
    rows.extend([1, 1])
    keyboard.adjust(*rows)
    return keyboard.as_markup()


def get_converter_currency_btns(
    *,
    prefix: str,
    include_menu: bool = False,
    back_callback: str | None = None,
) -> InlineKeyboardMarkup:
    btns = {
        "Юань": f"{prefix}cny_",
        "Евро": f"{prefix}eur_",
        "Доллар": f"{prefix}usd_",
        "Рубли": f"{prefix}rub_",
    }
    if back_callback:
        btns["Назад"] = back_callback
    if include_menu:
        btns["Меню"] = "mainmenu_"

    sizes = (2, 2)
    if back_callback and include_menu:
        sizes = (2, 2, 1, 1)
    elif back_callback or include_menu:
        sizes = (2, 2, 1)

    return get_inline_mix_btns(btns=btns, sizes=sizes)
