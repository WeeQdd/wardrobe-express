import os
from html import escape

from aiohttp import ClientSession
from aiogram import F, Router, types
from aiogram.filters import CommandStart
from aiogram.filters.state import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from database.orm_query import (
    orm_add_order_to_active_batch,
    orm_add_user,
    orm_cancel_active_batch,
    orm_delete_user_draft_order,
    orm_finalize_active_batch,
    orm_get_item,
    orm_get_order,
    orm_get_user,
    orm_get_user_draft_order,
    orm_get_user_order,
    orm_get_user_active_batch_orders,
    orm_get_user_saved_address,
    orm_get_user_saved_addresses,
    orm_update_order_status,
    orm_update_user_draft_order,
    orm_update_user_delivery_profile,
)
from filters.chat_types import ChatTypeFilter
from handlers.converter import calculate_order_pricing, converter_rate, normalize_currency
from handlers.menu_processing import get_menu_content
from kbds.inline import (
    get_batch_item_detail_btns,
    get_batch_item_list_btns,
    MenuCallBack,
    get_converter_currency_btns,
    get_inlineMix_btns,
    get_order_status_emoji,
    get_saved_addresses_btns,
    get_saved_profile_btns,
    get_user_order_detail_btns,
)
from kbds.reply import get_keyboard
from services.cdek_local_locator import find_nearest_pickup_points, format_pickup_option
from services.pricing import summarize_order_totals
from services.yandex_geocoder import YandexGeocoderError, geocode_address, reverse_geocode


user_private_router = Router()
user_private_router.message.filter(ChatTypeFilter(["private"]))


USER_BTN_CANCEL = "❌ Отмена"
USER_BTN_SEND_PHONE = "📞 Отправить номер телефона"
USER_BTN_SEND_LOCATION = "📍 Отправить геопозицию"


def is_cancel_text(value: str) -> bool:
    normalized = (value or "").strip().casefold()
    return normalized in {"отмена", USER_BTN_CANCEL.casefold()}


ORDER_STATUS_LABELS = {
    "new": "Новый",
    "confirmed": "Подтвержден",
    "awaiting_payment": "Ожидает оплату",
    "paid": "Оплачен",
    "purchased": "Выкуплен",
    "at_warehouse": "На складе",
    "in_transit": "В пути",
    "ready_for_pickup": "Готов к выдаче",
    "done": "Выдан",
    "cancelled": "Отменен",
}


# Конвертер вынесен в отдельный FSM, потому что у него свой короткий цикл
# ввода и он не влияет на пользовательские данные доставки.
class ConverterStates(StatesGroup):
    price = State()
    currency = State()
    msg_del = State()


# OrderFlow объединяет заказы из каталога и заказы по ссылке в один сценарий
# после того, как стали известны товар и размер.
class OrderFlow(StatesGroup):
    source_url = State()
    product_name = State()
    price = State()
    currency = State()
    size = State()
    saved_profile_choice = State()
    saved_address_choice = State()
    phone = State()
    delivery_address = State()
    pickup_choice = State()
    custom_pickup = State()
    edit_product_name = State()
    edit_size = State()
    edit_source_url = State()
    edit_price = State()


def format_price(value: float | None) -> str:
    if value is None or float(value) == 0:
        return "уточняется"
    return f"{round(float(value), 2)} руб."


def safe_text(value: str | None) -> str:
    return escape(value or "")


def is_valid_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def parse_price_input(value: str) -> float | None:
    normalized = (value or "").strip().replace(",", ".")
    try:
        price = float(normalized)
    except ValueError:
        return None
    if price <= 0:
        return None
    return round(price, 2)


def get_currency_prompt(currency_code: str) -> str:
    prompts = {
        "CNY": "Введите цену в юанях",
        "EUR": "Введите цену в евро",
        "USD": "Введите цену в долларах",
        "RUB": "Введите цену в рублях",
    }
    return prompts.get(currency_code, "Введите цену в выбранной валюте")


async def ask_for_order_currency(message: types.Message):
    await message.answer(
        "Выберите валюту товара для расчета стоимости.",
        reply_markup=get_converter_currency_btns(
            prefix="ordercurrency",
            back_callback=MenuCallBack(level=1, menu_name="order").pack(),
        ),
    )


# Сводка черновой пакетной заявки показывается до отправки всего пакета админам.
def format_batch_summary(orders: list) -> str:
    first = orders[0]
    totals = summarize_order_totals(orders)
    lines = [
        "Текущая заявка:",
        "",
    ]
    for index, order in enumerate(orders, start=1):
        lines.append(
            f"{index}. {safe_text(order.product_name)} | размер: {safe_text(order.size)} | "
            f"итого: {safe_text(format_price(order.total_price))}"
        )

    lines.extend(
        [
            "",
            f"Телефон: {safe_text(first.phone)}",
            f"Адрес: {safe_text(first.delivery_address or 'не указан')}",
            f"ПВЗ/постамат: {safe_text(first.nearest_pickup_point or 'не выбран')}",
            f"Сумма товаров: {safe_text(format_price(totals['subtotal']))}",
            f"Доставка: {safe_text(format_price(totals['delivery_fee']))}",
            f"Предварительный итог: {safe_text(format_price(totals['total_price']))}",
        ]
    )
    if totals["unknown_count"]:
        lines.append(f"Позиции с неуточненной ценой: {totals['unknown_count']}")

    return "\n".join(lines)


def format_batch_item_detail(order) -> str:
    source_url = order.source_url or "не указана"
    return (
        f"Позиция #{order.id}\n"
        f"Товар: {safe_text(order.product_name)}\n"
        f"Размер: {safe_text(order.size)}\n"
        f"Ссылка: {safe_text(source_url)}\n"
        f"Сумма товара: {safe_text(format_price(order.price))}\n"
        f"Доставка: {safe_text(format_price(order.delivery_fee))}\n"
        f"Итог: {safe_text(format_price(order.total_price))}"
    )


def can_user_cancel_order(status: str) -> bool:
    return status not in {"done", "cancelled"}


def format_user_order_detail(order) -> str:
    status_label = ORDER_STATUS_LABELS.get(order.status, order.status)
    source_url = f"Ссылка: {safe_text(order.source_url)}\n" if order.source_url else ""
    return (
        f"Заявка #{order.id}\n"
        f"Статус: {get_order_status_emoji(order.status)} {safe_text(status_label)}\n"
        f"Товар: {safe_text(order.product_name)}\n"
        f"{source_url}"
        f"Размер: {safe_text(order.size)}\n"
        f"Телефон: {safe_text(order.phone)}\n"
        f"Адрес: {safe_text(order.delivery_address or 'не указан')}\n"
        f"ПВЗ/постамат: {safe_text(order.nearest_pickup_point or 'не выбран')}\n"
        f"Сумма товара: {safe_text(format_price(order.price))}\n"
        f"Доставка: {safe_text(format_price(order.delivery_fee))}\n"
        f"Итог: {safe_text(format_price(order.total_price))}"
    )


def get_pickup_choice_markup(options_count: int) -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardBuilder()

    for index in range(options_count):
        keyboard.button(text=f"📍 Пункт {index + 1}", callback_data=f"pickup_select_{index}")

    keyboard.button(text="✏️ Указать свой ПВЗ", callback_data="pickup_manual")
    keyboard.button(text="⏭ Пропустить", callback_data="pickup_skip")
    keyboard.adjust(3, 1, 1)
    return keyboard.as_markup()


async def send_main_menu(message: types.Message, session: AsyncSession):
    media, reply_markup = await get_menu_content(session, level=0, menu_name="main")
    await message.answer_photo(media.media, caption=media.caption, reply_markup=reply_markup)


async def ask_for_phone(message: types.Message, current_phone: str | None = None):
    prompt = "Отправьте номер телефона или введите его вручную."
    if current_phone:
        prompt += f"\nСохраненный номер: {current_phone}"

    await message.answer(
        prompt,
        reply_markup=get_keyboard(
            USER_BTN_SEND_PHONE,
            USER_BTN_CANCEL,
            request_contact=0,
            sizes=(1, 1),
        ),
    )


async def ask_for_address(message: types.Message, current_address: str | None = None):
    prompt = (
        "Введите адрес доставки или отправьте геопозицию. "
        "По этим данным бот попробует определить ближайший пункт СДЭК."
    )
    if current_address:
        prompt += f"\nТекущий адрес: {current_address}"

    await message.answer(
        prompt,
        reply_markup=get_keyboard(
            USER_BTN_SEND_LOCATION,
            USER_BTN_CANCEL,
            request_location=0,
            sizes=(1, 1),
        ),
    )


# Эти функции приводят текстовый адрес или геопозицию Telegram к единому виду
# и подбирают ближайшие пункты выдачи СДЭК.
async def resolve_pickup_by_address(address: str) -> dict:
    async with ClientSession() as http_session:
        geocoded = await geocode_address(http_session, address)
        pickup_points = find_nearest_pickup_points(
            latitude=geocoded.latitude,
            longitude=geocoded.longitude,
            city=geocoded.city,
            limit=3,
        )

    return {
        "delivery_address": geocoded.formatted_address,
        "delivery_lat": geocoded.latitude,
        "delivery_lon": geocoded.longitude,
        "pickup_candidates": [format_pickup_option(item) for item in pickup_points],
        "nearest_pickup_point": None,
    }


async def resolve_pickup_by_location(latitude: float, longitude: float) -> dict:
    async with ClientSession() as http_session:
        geocoded = await reverse_geocode(http_session, latitude, longitude)
        pickup_points = find_nearest_pickup_points(
            latitude=latitude,
            longitude=longitude,
            city=geocoded.city,
            limit=3,
        )

    return {
        "delivery_address": geocoded.formatted_address,
        "delivery_lat": latitude,
        "delivery_lon": longitude,
        "pickup_candidates": [format_pickup_option(item) for item in pickup_points],
        "nearest_pickup_point": None,
    }


async def prompt_pickup_selection(message: types.Message, state: FSMContext, resolved: dict):
    pickup_candidates = resolved.get("pickup_candidates") or []
    await state.update_data(**resolved)

    if pickup_candidates:
        await state.set_state(OrderFlow.pickup_choice)
        options_text = "\n".join(
            f"{index}. {option}" for index, option in enumerate(pickup_candidates, start=1)
        )
        await message.answer(
            f"Адрес: {resolved['delivery_address']}\n"
            "Выберите ближайший пункт кнопкой ниже или укажите свой ПВЗ вручную.\n\n"
            f"{options_text}",
            reply_markup=get_pickup_choice_markup(len(pickup_candidates)),
        )
        return

    await state.update_data(nearest_pickup_point=None)
    await state.set_state(OrderFlow.custom_pickup)
    await message.answer(
        'Ближайшие пункты не найдены.\nВведите адрес ПВЗ вручную или отправьте "." чтобы пропустить.',
        reply_markup=types.ReplyKeyboardRemove(),
    )


async def handle_delivery_text(message: types.Message, state: FSMContext):
    address = message.text.strip()
    if is_cancel_text(address):
        await state.clear()
        await message.answer("Оформление заказа отменено.", reply_markup=types.ReplyKeyboardRemove())
        return

    if len(address) < 5:
        await message.answer("Введите более полный адрес или хотя бы город и улицу.")
        return

    try:
        resolved = await resolve_pickup_by_address(address)
    except YandexGeocoderError as exc:
        await state.update_data(
            delivery_address=address,
            delivery_lat=None,
            delivery_lon=None,
            nearest_pickup_point=None,
            pickup_candidates=[],
        )
        await state.set_state(OrderFlow.custom_pickup)
        await message.answer(
            f"Не удалось автоматически определить ближайшие пункты: {safe_text(str(exc))}\n"
            'Введите адрес ПВЗ вручную или отправьте "." чтобы пропустить.',
            reply_markup=types.ReplyKeyboardRemove(),
        )
        return

    await prompt_pickup_selection(message, state, resolved)


async def handle_delivery_location(message: types.Message, state: FSMContext):
    location = message.location
    try:
        resolved = await resolve_pickup_by_location(location.latitude, location.longitude)
    except YandexGeocoderError as exc:
        await state.update_data(
            delivery_address="Геопозиция получена",
            delivery_lat=location.latitude,
            delivery_lon=location.longitude,
            nearest_pickup_point=None,
            pickup_candidates=[],
        )
        await state.set_state(OrderFlow.custom_pickup)
        await message.answer(
            f"Геопозиция сохранена, но ближайшие пункты определить не удалось: {safe_text(str(exc))}\n"
            'Введите адрес ПВЗ вручную или отправьте "." чтобы пропустить.',
            reply_markup=types.ReplyKeyboardRemove(),
        )
        return

    await prompt_pickup_selection(message, state, resolved)


def build_order_data_from_saved_address(state_data: dict, user, saved_address) -> dict:
    return {
        **state_data,
        "phone": user.phone,
        "delivery_address": saved_address.address,
        "delivery_lat": float(saved_address.delivery_lat) if saved_address.delivery_lat is not None else None,
        "delivery_lon": float(saved_address.delivery_lon) if saved_address.delivery_lon is not None else None,
        "nearest_pickup_point": saved_address.pickup_point,
        "comment": None,
    }


async def show_batch_actions(message: types.Message, session: AsyncSession, telegram_user_id: int, added_order_id: int | None = None):
    active_orders = await orm_get_user_active_batch_orders(session, telegram_user_id)
    if not active_orders:
        await message.answer("Текущая заявка пуста.")
        return

    prefix = ""
    if added_order_id is not None:
        prefix = f"Товар добавлен в заявку. Позиция #{added_order_id} сохранена.\n\n"

    await message.answer(
        prefix + format_batch_summary(active_orders),
        reply_markup=get_batch_item_list_btns(active_orders),
    )


async def finalize_draft_order(
    message: types.Message,
    state: FSMContext,
    session: AsyncSession,
    telegram_user: types.User | None = None,
):
    data = await state.get_data()
    actor = telegram_user or message.from_user
    # Перед добавлением товара в текущий пакет сохраняем актуальные
    # контактные данные и адрес в профиле пользователя.
    await orm_update_user_delivery_profile(
        session,
        actor.id,
        phone=data["phone"],
        delivery_address=data.get("delivery_address"),
        delivery_lat=data.get("delivery_lat"),
        delivery_lon=data.get("delivery_lon"),
        pickup_point=data.get("nearest_pickup_point"),
    )
    order, _ = await orm_add_order_to_active_batch(session, actor.id, data)
    await state.clear()
    await show_batch_actions(message, session, actor.id, added_order_id=order.id)


async def proceed_after_size(message: types.Message, state: FSMContext, session: AsyncSession):
    user = await orm_get_user(session, message.from_user.id)
    state_data = await state.get_data()

    # Если у пользователя уже есть активный пакет, новые товары должны
    # использовать последний сохраненный профиль доставки без повторных вопросов.
    if user and user.active_batch_code and user.phone and user.default_delivery_address:
        saved_addresses = await orm_get_user_saved_addresses(session, message.from_user.id, limit=1)
        if saved_addresses:
            order_data = build_order_data_from_saved_address(state_data, user, saved_addresses[0])
            await orm_add_order_to_active_batch(session, message.from_user.id, order_data)
            await state.clear()
            await show_batch_actions(message, session, message.from_user.id)
            return

    if user and user.phone and user.default_delivery_address:
        await state.set_state(OrderFlow.saved_profile_choice)
        await message.answer(
            "У вас есть сохраненные телефон и адреса доставки. Использовать их для новой заявки?",
            reply_markup=get_saved_profile_btns(),
        )
        return

    if user and user.phone:
        await state.update_data(phone=user.phone)
        await state.set_state(OrderFlow.delivery_address)
        await ask_for_address(message, current_address=user.default_delivery_address)
        return

    await state.set_state(OrderFlow.phone)
    await ask_for_phone(message, current_phone=user.phone if user else None)


def format_admin_batch_text(orders: list, user, telegram_user: types.User, batch_code: str) -> str:
    first = orders[0]
    totals = summarize_order_totals(orders)
    username = f"@{telegram_user.username}" if telegram_user.username else "не указан"
    lines = [
        "<strong>Новая заявка на доставку</strong>",
        f"Пакет: <code>{safe_text(batch_code)}</code>",
        f"Клиент: {safe_text(user.first_name or telegram_user.first_name or '')} {safe_text(user.last_name or telegram_user.last_name or '')}".strip(),
        f"Username: {safe_text(username)}",
        f"Telegram ID: <code>{telegram_user.id}</code>",
        f"Телефон: {safe_text(first.phone)}",
        f"Адрес: {safe_text(first.delivery_address or 'не указан')}",
        f"ПВЗ/постамат: {safe_text(first.nearest_pickup_point or 'не выбран')}",
        "",
        "<strong>Товары:</strong>",
    ]

    for index, order in enumerate(orders, start=1):
        source = "не указан"
        item_lines = [
            f"{index}. {safe_text(order.product_name)}",
            f"Размер: {safe_text(order.size)}",
            f"Источник: {safe_text(source)}",
            f"Сумма товара: {safe_text(format_price(order.price))}",
            f"Доставка: {safe_text(format_price(order.delivery_fee))}",
            f"Итог: {safe_text(format_price(order.total_price))}",
        ]
        if order.source_url:
            item_lines.append(f"Ссылка: {safe_text(order.source_url)}")
        lines.append("\n".join(item_lines))

    lines.extend(
        [
            "",
            "<strong>Итоги по пакету:</strong>",
            f"Сумма товаров: {safe_text(format_price(totals['subtotal']))}",
            f"Доставка: {safe_text(format_price(totals['delivery_fee']))}",
            f"Предварительный итог: {safe_text(format_price(totals['total_price']))}",
        ]
    )
    if totals["unknown_count"]:
        lines.append(f"Позиции с неуточненной ценой: {totals['unknown_count']}")

    return "\n".join(lines)


# Сообщение в админский чат формируется отдельно, потому что операторам
# нужны подробные суммы и ссылки по каждой позиции.
async def send_batch_to_admin_chat(bot, telegram_user: types.User, orders: list, batch_code: str, session: AsyncSession) -> bool:
    admin_group_id = os.getenv("ADMIN_GROUP_ID")
    if not admin_group_id or not admin_group_id.lstrip("-").isdigit():
        return False

    user = await orm_get_user(session, telegram_user.id)
    if user is None:
        return False

    text = format_admin_batch_text(orders, user, telegram_user, batch_code)
    await bot.send_message(int(admin_group_id), text)
    return True


@user_private_router.message(CommandStart())
async def start_cmd(message: types.Message, session: AsyncSession):
    await orm_add_user(
        session,
        user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
    )
    await send_main_menu(message, session)


@user_private_router.message(StateFilter("*"), F.text.casefold() == "отмена")
async def cancel_any_flow(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        return

    await state.clear()
    await message.answer("Текущее действие отменено.", reply_markup=types.ReplyKeyboardRemove())


@user_private_router.callback_query(F.data.startswith("mainmenu_"))
async def return_menu(callback: types.CallbackQuery, session: AsyncSession):
    await callback.message.delete()
    await send_main_menu(callback.message, session)


@user_private_router.callback_query(MenuCallBack.filter())
async def user_menu(
    callback: types.CallbackQuery,
    callback_data: MenuCallBack,
    session: AsyncSession,
):
    result = await get_menu_content(
        session,
        level=callback_data.level,
        menu_name=callback_data.menu_name,
        category=callback_data.category,
        page=callback_data.page,
        user_id=callback.from_user.id,
    )

    if result is None:
        await callback.answer(text="Товары закончились", show_alert=True)
        return

    media, reply_markup = result
    await callback.message.edit_media(media=media, reply_markup=reply_markup)
    await callback.answer()


@user_private_router.callback_query(F.data.startswith("userorder_"))
async def user_order_detail(callback: types.CallbackQuery, session: AsyncSession):
    order_id = int(callback.data.split("_")[-1])
    order = await orm_get_user_order(session, callback.from_user.id, order_id)
    if order is None:
        await callback.answer("Заявка не найдена", show_alert=True)
        return

    await callback.message.edit_caption(
        caption=format_user_order_detail(order),
        reply_markup=get_user_order_detail_btns(
            order.id,
            can_cancel=can_user_cancel_order(order.status),
        ),
    )
    await callback.answer()


@user_private_router.callback_query(F.data.startswith("userordercancel_"))
async def user_order_cancel(callback: types.CallbackQuery, session: AsyncSession):
    order_id = int(callback.data.split("_")[-1])
    order = await orm_get_user_order(session, callback.from_user.id, order_id)
    if order is None:
        await callback.answer("Заявка не найдена", show_alert=True)
        return

    if not can_user_cancel_order(order.status):
        await callback.answer("Эту заявку уже нельзя отменить", show_alert=True)
        return

    await orm_update_order_status(session, order.id, "cancelled")
    order = await orm_get_order(session, order.id)
    await callback.message.edit_caption(
        caption=format_user_order_detail(order),
        reply_markup=get_user_order_detail_btns(order.id, can_cancel=False),
    )
    await callback.answer("Заявка отменена")


# Заказ по ссылке стартует с URL, а заказ из каталога входит в тот же
# сценарий позже, когда данные о товаре уже известны.
@user_private_router.callback_query(F.data == "ordercurrency_menu")
async def order_currency_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(OrderFlow.currency)
    await callback.message.edit_text(
        "Выберите валюту товара для расчета стоимости.",
        reply_markup=get_converter_currency_btns(
            prefix="ordercurrency",
            back_callback=MenuCallBack(level=1, menu_name="order").pack(),
        ),
    )
    await callback.answer()


@user_private_router.callback_query(F.data.startswith("ordercurrency"))
async def order_currency_choice(callback: types.CallbackQuery, state: FSMContext):
    raw_currency = callback.data.removeprefix("ordercurrency").rstrip("_")
    try:
        currency = normalize_currency(raw_currency)
    except ValueError:
        await callback.answer("Неизвестная валюта", show_alert=True)
        return

    await state.update_data(source_currency=currency)
    await state.set_state(OrderFlow.price)
    await callback.message.edit_text(
        get_currency_prompt(currency),
        reply_markup=get_inlineMix_btns(btns={"Назад": "ordercurrency_menu"}),
    )
    await callback.answer()


@user_private_router.callback_query(F.data == "start_link_order")
async def start_link_order(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(OrderFlow.source_url)
    await callback.message.answer("Отправьте ссылку на товар.")
    await callback.answer()


@user_private_router.message(OrderFlow.source_url, F.text)
async def link_order_get_url(message: types.Message, state: FSMContext):
    url = message.text.strip()
    if not is_valid_url(url):
        await message.answer("Отправьте корректную ссылку, которая начинается с http:// или https://")
        return

    await state.update_data(source_url=url)
    await state.set_state(OrderFlow.product_name)
    await message.answer("Ссылка сохранена. Введите название товара.")
    return


@user_private_router.message(OrderFlow.product_name, F.text)
async def link_order_get_name(message: types.Message, state: FSMContext):
    title = message.text.strip()
    if len(title) < 2:
        await message.answer("Введите более понятное название товара.")
        return

    await state.update_data(product_name=title)
    await state.set_state(OrderFlow.currency)
    await ask_for_order_currency(message)


@user_private_router.message(OrderFlow.price, F.text)
async def link_order_get_price(message: types.Message, state: FSMContext):
    price = parse_price_input(message.text)
    if price is None:
        await message.answer("Введите корректную цену товара числом, например 129.99")
        return

    data = await state.get_data()
    currency = data.get("source_currency")
    if not currency:
        await state.update_data(source_price=price)
        await state.set_state(OrderFlow.currency)
        await ask_for_order_currency(message)
        return

    try:
        async with ClientSession() as http_session:
            pricing = await calculate_order_pricing(http_session, price, currency)
    except Exception:
        await message.answer(
            "Не удалось рассчитать стоимость по курсу. Попробуйте еще раз позже или выберите другую валюту."
        )
        return

    await state.update_data(
        source_price=price,
        price=pricing["price"],
        pricing={
            "price": pricing["price"],
            "service_fee": pricing["service_fee"],
            "delivery_fee": pricing["delivery_fee"],
            "total_price": pricing["total_price"],
        },
        rate_to_rub=pricing["rate_to_rub"],
    )
    await state.set_state(OrderFlow.size)
    await message.answer(
        "Расчет сохранен:\n"
        f"Цена товара в рублях: {format_price(pricing['price'])}\n"
        f"Расходы до Москвы: {format_price(pricing['service_fee'])}\n"
        f"Доставка по России: {format_price(pricing['delivery_fee'])}\n"
        f"Итог: {format_price(pricing['total_price'])}\n\n"
        'Введите размер товара или "." если размер не важен.',
        reply_markup=types.ReplyKeyboardRemove(),
    )


@user_private_router.message(OrderFlow.currency, F.text)
async def link_order_get_currency(message: types.Message, state: FSMContext):
    currency_raw = message.text.strip()
    if is_cancel_text(currency_raw):
        await state.clear()
        await message.answer("Оформление заказа отменено.", reply_markup=types.ReplyKeyboardRemove())
        return

    try:
        currency = normalize_currency(currency_raw)
    except ValueError:
        await message.answer("Выберите валюту кнопкой ниже или введите: юань, евро, доллар, рубли.")
        await ask_for_order_currency(message)
        return

    await state.update_data(source_currency=currency)
    await state.set_state(OrderFlow.price)
    await message.answer(get_currency_prompt(currency), reply_markup=types.ReplyKeyboardRemove())


@user_private_router.callback_query(F.data.regexp(r"^order_\d+$"))
async def order_item_start(
    callback: types.CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
):
    item_id = int(callback.data.split("_")[-1])
    item = await orm_get_item(session, item_id)
    if item is None:
        await callback.answer("Товар не найден", show_alert=True)
        return

    await state.clear()
    await state.update_data(
        item_id=item.id,
        product_name=item.name,
        price=float(item.price),
    )
    await state.set_state(OrderFlow.size)
    await callback.message.answer(
        f"Оформление заказа: {item.name}\nВведите размер или комментарий по размеру."
    )
    await callback.answer()


@user_private_router.message(OrderFlow.size, F.text)
async def order_get_size(message: types.Message, state: FSMContext, session: AsyncSession):
    text = message.text.strip()
    size = "не указан" if text == "." else text
    await state.update_data(size=size)
    await proceed_after_size(message, state, session)


# Сохраненные адреса принадлежат только текущему пользователю Telegram
# и позволяют не вводить одни и те же данные для каждого нового пакета.
@user_private_router.callback_query(OrderFlow.saved_profile_choice, F.data == "order_use_saved")
async def order_use_saved_data(
    callback: types.CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
):
    user = await orm_get_user(session, callback.from_user.id)
    saved_addresses = await orm_get_user_saved_addresses(session, callback.from_user.id, limit=5)
    if user is None or not user.phone or not saved_addresses:
        await callback.answer("Сохраненные данные не найдены", show_alert=True)
        return

    await state.update_data(phone=user.phone)
    if len(saved_addresses) == 1:
        order_data = build_order_data_from_saved_address(await state.get_data(), user, saved_addresses[0])
        await orm_add_order_to_active_batch(session, callback.from_user.id, order_data)
        await state.clear()
        await show_batch_actions(callback.message, session, callback.from_user.id)
        await callback.answer()
        return

    await state.set_state(OrderFlow.saved_address_choice)
    await callback.message.answer(
        "Выберите один из сохраненных адресов.",
        reply_markup=get_saved_addresses_btns(saved_addresses),
    )
    await callback.answer()


@user_private_router.callback_query(OrderFlow.saved_address_choice, F.data.startswith("saved_address_"))
async def order_select_saved_address(
    callback: types.CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
):
    address_id = int(callback.data.split("_")[-1])
    user = await orm_get_user(session, callback.from_user.id)
    saved_address = await orm_get_user_saved_address(session, callback.from_user.id, address_id)
    if user is None or saved_address is None:
        await callback.answer("Адрес не найден", show_alert=True)
        return

    order_data = build_order_data_from_saved_address(await state.get_data(), user, saved_address)
    await orm_add_order_to_active_batch(session, callback.from_user.id, order_data)
    await state.clear()
    await show_batch_actions(callback.message, session, callback.from_user.id)
    await callback.answer()


@user_private_router.callback_query(F.data == "order_use_new")
async def order_use_new_data(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    user = await orm_get_user(session, callback.from_user.id)
    await state.set_state(OrderFlow.phone)
    await ask_for_phone(callback.message, current_phone=user.phone if user else None)
    await callback.answer()


@user_private_router.message(OrderFlow.phone, F.contact)
async def order_get_phone_contact(
    message: types.Message,
    state: FSMContext,
    session: AsyncSession,
):
    phone = message.contact.phone_number
    await state.update_data(phone=phone)
    await orm_add_user(
        session,
        user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
        phone=phone,
    )
    await state.set_state(OrderFlow.delivery_address)
    user = await orm_get_user(session, message.from_user.id)
    await ask_for_address(message, current_address=user.default_delivery_address if user else None)


@user_private_router.message(OrderFlow.phone, F.text)
async def order_get_phone_text(
    message: types.Message,
    state: FSMContext,
    session: AsyncSession,
):
    phone = message.text.strip()
    if len(phone) < 10:
        await message.answer("Введите корректный номер телефона.")
        return

    await state.update_data(phone=phone)
    await orm_add_user(
        session,
        user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
        phone=phone,
    )
    await state.set_state(OrderFlow.delivery_address)
    user = await orm_get_user(session, message.from_user.id)
    await ask_for_address(message, current_address=user.default_delivery_address if user else None)


@user_private_router.message(OrderFlow.delivery_address, F.location)
async def order_get_location(message: types.Message, state: FSMContext):
    await handle_delivery_location(message, state)


@user_private_router.message(OrderFlow.delivery_address, F.text)
async def order_get_address(message: types.Message, state: FSMContext):
    await handle_delivery_text(message, state)


# Выбор ПВЗ вынесен в отдельный шаг, чтобы пользователь мог заменить
# автоматически предложенный пункт без перезапуска всего сценария заказа.
@user_private_router.callback_query(OrderFlow.pickup_choice, F.data.startswith("pickup_select_"))
async def pickup_select(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    options = data.get("pickup_candidates") or []
    option_index = int(callback.data.split("_")[-1])

    if option_index < 0 or option_index >= len(options):
        await callback.answer("Пункт не найден", show_alert=True)
        return

    selected_point = options[option_index]
    await state.update_data(nearest_pickup_point=selected_point)
    await callback.message.answer(f"Выбран пункт:\n{selected_point}")
    await finalize_draft_order(callback.message, state, session, callback.from_user)
    await callback.answer()


@user_private_router.callback_query(OrderFlow.pickup_choice, F.data == "pickup_manual")
async def pickup_manual(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(OrderFlow.custom_pickup)
    await callback.message.answer('Введите адрес ПВЗ вручную или отправьте "." чтобы пропустить.')
    await callback.answer()


@user_private_router.callback_query(OrderFlow.pickup_choice, F.data == "pickup_skip")
async def pickup_skip(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    await state.update_data(nearest_pickup_point=None)
    await finalize_draft_order(callback.message, state, session, callback.from_user)
    await callback.answer()


@user_private_router.message(OrderFlow.custom_pickup, F.text)
async def order_custom_pickup(message: types.Message, state: FSMContext, session: AsyncSession):
    custom_pickup = message.text.strip()
    if custom_pickup == ".":
        await state.update_data(nearest_pickup_point=None)
    else:
        if len(custom_pickup) < 5:
            await message.answer('Введите более полный адрес ПВЗ или отправьте "." чтобы пропустить.')
            return
        await state.update_data(nearest_pickup_point=custom_pickup)

    await finalize_draft_order(message, state, session)


# Действия пакета отражают основной сценарий бота:
# сначала собрать несколько товаров, потом отправить их одной заявкой.
@user_private_router.callback_query(F.data == "batch_open")
async def batch_open(callback: types.CallbackQuery, session: AsyncSession):
    active_orders = await orm_get_user_active_batch_orders(session, callback.from_user.id)
    if not active_orders:
        await callback.answer("Текущая заявка пуста", show_alert=True)
        return

    await callback.message.answer(
        format_batch_summary(active_orders),
        reply_markup=get_batch_item_list_btns(active_orders),
    )
    await callback.answer()


@user_private_router.callback_query(F.data.startswith("batchitem_"))
async def batch_item_open(callback: types.CallbackQuery, session: AsyncSession):
    order_id = int(callback.data.split("_")[-1])
    order = await orm_get_user_draft_order(session, callback.from_user.id, order_id)
    if order is None:
        await callback.answer("Позиция не найдена", show_alert=True)
        return

    await callback.message.answer(
        format_batch_item_detail(order),
        reply_markup=get_batch_item_detail_btns(order.id),
    )
    await callback.answer()


@user_private_router.callback_query(F.data.startswith("batchdelete_"))
async def batch_item_delete(callback: types.CallbackQuery, session: AsyncSession):
    order_id = int(callback.data.split("_")[-1])
    deleted = await orm_delete_user_draft_order(session, callback.from_user.id, order_id)
    if not deleted:
        await callback.answer("Позиция не найдена", show_alert=True)
        return

    active_orders = await orm_get_user_active_batch_orders(session, callback.from_user.id)
    if not active_orders:
        await callback.message.answer("Текущая заявка теперь пуста.")
    else:
        await callback.message.answer(
            "Позиция удалена.\n\n" + format_batch_summary(active_orders),
            reply_markup=get_batch_item_list_btns(active_orders),
        )
    await callback.answer("Позиция удалена")


async def start_batch_item_edit(
    callback: types.CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    *,
    field_state,
    prompt: str,
):
    order_id = int(callback.data.split("_")[-1])
    order = await orm_get_user_draft_order(session, callback.from_user.id, order_id)
    if order is None:
        await callback.answer("Позиция не найдена", show_alert=True)
        return

    await state.clear()
    await state.update_data(edit_order_id=order.id)
    await state.set_state(field_state)
    await callback.message.answer(prompt)
    await callback.answer()


@user_private_router.callback_query(F.data.startswith("batchedit_name_"))
async def batch_edit_name_start(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    await start_batch_item_edit(
        callback,
        state,
        session,
        field_state=OrderFlow.edit_product_name,
        prompt="Введите новое название товара.",
    )


@user_private_router.callback_query(F.data.startswith("batchedit_size_"))
async def batch_edit_size_start(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    await start_batch_item_edit(
        callback,
        state,
        session,
        field_state=OrderFlow.edit_size,
        prompt='Введите новый размер или "." если размер не указан.',
    )


@user_private_router.callback_query(F.data.startswith("batchedit_url_"))
async def batch_edit_url_start(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    await start_batch_item_edit(
        callback,
        state,
        session,
        field_state=OrderFlow.edit_source_url,
        prompt='Отправьте новую ссылку на товар или "." чтобы убрать ссылку.',
    )


@user_private_router.callback_query(F.data.startswith("batchedit_price_"))
async def batch_edit_price_start(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    await start_batch_item_edit(
        callback,
        state,
        session,
        field_state=OrderFlow.edit_price,
        prompt="Введите новую цену товара в рублях.",
    )


@user_private_router.callback_query(F.data == "batch_cancel")
async def batch_cancel(callback: types.CallbackQuery, session: AsyncSession):
    deleted_count = await orm_cancel_active_batch(session, callback.from_user.id)
    if not deleted_count:
        await callback.answer("Текущая заявка пуста", show_alert=True)
        return

    await callback.message.answer("Текущая заявка сброшена.")
    await callback.answer()


@user_private_router.callback_query(F.data == "batch_finalize")
async def batch_finalize(callback: types.CallbackQuery, session: AsyncSession):
    orders, batch_code = await orm_finalize_active_batch(session, callback.from_user.id)
    if not orders or not batch_code:
        await callback.answer("Текущая заявка пуста", show_alert=True)
        return

    sent_to_admins = False
    try:
        sent_to_admins = await send_batch_to_admin_chat(
            callback.bot,
            callback.from_user,
            orders,
            batch_code,
            session,
        )
    except Exception:
        sent_to_admins = False

    totals = summarize_order_totals(orders)
    text = (
        f"Заявка отправлена. Пакет: {batch_code}\n"
        f"Позиций: {len(orders)}\n"
        f"Предварительный итог: {format_price(totals['total_price'])}\n"
        f"Статус: {ORDER_STATUS_LABELS['new']}"
    )
    if totals["unknown_count"]:
        text += f"\nПозиции с неуточненной ценой: {totals['unknown_count']}"
    if not sent_to_admins:
        text += "\nПредупреждение: чат администраторов не настроен или сообщение не удалось отправить."

    await callback.message.answer(
        text,
        reply_markup=get_inlineMix_btns(
            btns={
                "📦 Мои заявки": MenuCallBack(level=1, menu_name="myorders").pack(),
                "👤 Профиль": MenuCallBack(level=1, menu_name="profile").pack(),
                "🏠 В меню": MenuCallBack(level=0, menu_name="main").pack(),
            },
            sizes=(1, 1, 1),
        ),
    )
    await callback.answer()


async def finish_batch_item_edit(message: types.Message, state: FSMContext, session: AsyncSession, **kwargs):
    data = await state.get_data()
    order_id = data.get("edit_order_id")
    if not order_id:
        await state.clear()
        await message.answer("Не удалось определить позицию для редактирования.")
        return

    order = await orm_update_user_draft_order(
        session,
        message.from_user.id,
        int(order_id),
        **kwargs,
    )
    await state.clear()
    if order is None:
        await message.answer("Позиция не найдена.")
        return

    await message.answer(
        "Позиция обновлена.\n\n" + format_batch_item_detail(order),
        reply_markup=get_batch_item_detail_btns(order.id),
    )


@user_private_router.message(OrderFlow.edit_product_name, F.text)
async def batch_edit_name_finish(message: types.Message, state: FSMContext, session: AsyncSession):
    product_name = message.text.strip()
    if len(product_name) < 2:
        await message.answer("Введите более понятное название товара.")
        return

    await finish_batch_item_edit(message, state, session, product_name=product_name)


@user_private_router.message(OrderFlow.edit_size, F.text)
async def batch_edit_size_finish(message: types.Message, state: FSMContext, session: AsyncSession):
    size = message.text.strip()
    if size == ".":
        size = "не указан"
    elif len(size) < 1:
        await message.answer("Введите размер товара.")
        return

    await finish_batch_item_edit(message, state, session, size=size)


@user_private_router.message(OrderFlow.edit_source_url, F.text)
async def batch_edit_url_finish(message: types.Message, state: FSMContext, session: AsyncSession):
    source_url = message.text.strip()
    if source_url == ".":
        source_url = None
    elif not is_valid_url(source_url):
        await message.answer('Отправьте корректную ссылку или "." чтобы убрать ссылку.')
        return

    await finish_batch_item_edit(message, state, session, source_url=source_url)


@user_private_router.message(OrderFlow.edit_price, F.text)
async def batch_edit_price_finish(message: types.Message, state: FSMContext, session: AsyncSession):
    price = parse_price_input(message.text)
    if price is None:
        await message.answer("Введите корректную цену товара в рублях, например 4990.")
        return

    await finish_batch_item_edit(message, state, session, price=price)


# Конвертер специально оставлен вне схемы "одно сообщение",
# потому что ему нужен отдельный числовой ввод от пользователя.
@user_private_router.callback_query(F.data.startswith("converter_"))
async def converter_menu(callback: types.CallbackQuery):
    await callback.message.edit_caption(
        caption="Выберите валюту для расчета стоимости товара и его доставки.",
        reply_markup=get_inlineMix_btns(
            btns={
                "🇨🇳 Юань": "convertercny_",
                "🇪🇺 Евро": "convertereur_",
                "🇺🇸 Доллар": "converterusd_",
                "🏠 Меню": "mainmenu_",
            },
            sizes=(2, 1, 1),
        ),
    )


@user_private_router.callback_query(F.data.startswith("convertercny_"))
async def converter_cny(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_caption(
        caption="Введите цену в юанях",
        reply_markup=get_inlineMix_btns(btns={"⬅️ Назад": "converter_"}),
    )
    await state.update_data(currency="cny", msg_del=callback.message.message_id)
    await state.set_state(ConverterStates.price)


@user_private_router.callback_query(F.data.startswith("convertereur_"))
async def converter_eur(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_caption(
        caption="Введите цену в евро",
        reply_markup=get_inlineMix_btns(btns={"⬅️ Назад": "converter_"}),
    )
    await state.update_data(currency="eur", msg_del=callback.message.message_id)
    await state.set_state(ConverterStates.price)


@user_private_router.callback_query(F.data.startswith("converterusd_"))
async def converter_usd(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_caption(
        caption="Введите цену в долларах",
        reply_markup=get_inlineMix_btns(btns={"⬅️ Назад": "converter_"}),
    )
    await state.update_data(currency="usd", msg_del=callback.message.message_id)
    await state.set_state(ConverterStates.price)


@user_private_router.message(ConverterStates.price)
async def process_price(message: types.Message, state: FSMContext):
    await message.delete()
    data = await state.get_data()
    currency = data.get("currency")
    msg = data.get("msg_del")

    if msg:
        await message.bot.delete_message(message.chat.id, msg)

    if message.text and message.text.isdigit():
        price = int(message.text)

        async with ClientSession() as http_session:
            result = await converter_rate(http_session, price, currency)

        await message.bot.send_message(
            message.chat.id,
            result,
            reply_markup=get_inlineMix_btns(
                btns={
                    "📝 Оформить доставку": MenuCallBack(level=1, menu_name="order").pack(),
                    "🏠 В меню": "mainmenu_",
                },
                sizes=(1, 1),
            ),
        )
        await state.clear()
    else:
        await state.clear()
        await message.answer("Вы ввели недопустимые данные")
