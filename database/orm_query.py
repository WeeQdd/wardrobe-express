import math
from uuid import uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Banner, Category, ChatAdmin, Items, Order, SavedAddress, User
from services.pricing import calculate_order_totals


class Paginator:
    def __init__(self, array: list | tuple, page: int = 1, per_page: int = 1):
        self.array = array
        self.per_page = per_page
        self.page = page
        self.len = len(self.array)
        self.pages = math.ceil(self.len / self.per_page) if self.per_page else 0

    def _get_slice(self):
        start = (self.page - 1) * self.per_page
        stop = start + self.per_page
        return self.array[start:stop]

    def get_page(self):
        return self._get_slice()

    def has_next(self):
        if self.page < self.pages:
            return self.page + 1
        return False

    def has_previous(self):
        if self.page > 1:
            return self.page - 1
        return False


async def orm_add_banner_description(session: AsyncSession, data: dict):
    result = await session.execute(select(Banner))
    existing = {banner.name: banner for banner in result.scalars().all()}

    should_commit = False
    to_add = []

    for name, description in data.items():
        banner = existing.get(name)
        if banner is None:
            to_add.append(Banner(name=name, description=description))
            should_commit = True
            continue

        if banner.description != description:
            banner.description = description
            should_commit = True

    if to_add:
        session.add_all(to_add)

    if should_commit:
        await session.commit()


async def orm_change_banner_image(session: AsyncSession, name: str, image: str):
    await session.execute(update(Banner).where(Banner.name == name).values(image=image))
    await session.commit()


async def orm_get_banner(session: AsyncSession, page: str):
    result = await session.execute(select(Banner).where(Banner.name == page))
    return result.scalar_one_or_none()


async def orm_get_categories(session: AsyncSession):
    result = await session.execute(select(Category).order_by(Category.id))
    return result.scalars().all()


async def orm_create_categories(session: AsyncSession, categories: list[str]):
    result = await session.execute(select(Category))
    if result.first():
        return

    session.add_all([Category(name=name) for name in categories])
    await session.commit()


async def orm_add_item(session: AsyncSession, data: dict):
    item = Items(
        name=data["name"],
        size=data["size"],
        price=float(data["price"]),
        image=data["image"],
        category_id=int(data["category"]),
    )
    session.add(item)
    await session.commit()


async def orm_get_items(session: AsyncSession, category_id: int):
    result = await session.execute(
        select(Items).where(Items.category_id == int(category_id)).order_by(Items.id.desc())
    )
    return result.scalars().all()


async def orm_get_item(session: AsyncSession, item_id: int):
    result = await session.execute(select(Items).where(Items.id == item_id))
    return result.scalar_one_or_none()


async def orm_update_item(session: AsyncSession, item_id: int, data: dict):
    await session.execute(
        update(Items)
        .where(Items.id == item_id)
        .values(
            name=data["name"],
            size=data["size"],
            price=float(data["price"]),
            image=data["image"],
            category_id=int(data["category"]),
        )
    )
    await session.commit()


async def orm_delete_item(session: AsyncSession, item_id: int):
    await session.execute(delete(Items).where(Items.id == item_id))
    await session.commit()


async def orm_add_user(
    session: AsyncSession,
    user_id: int,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    phone: str | None = None,
):
    user = await orm_get_user(session, user_id)
    if user is None:
        session.add(
            User(
                user_id=user_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                phone=phone,
            )
        )
    else:
        user.username = username or user.username
        user.first_name = first_name or user.first_name
        user.last_name = last_name or user.last_name
        if phone:
            user.phone = phone
    await session.commit()


async def orm_get_user(session: AsyncSession, telegram_user_id: int):
    result = await session.execute(select(User).where(User.user_id == telegram_user_id))
    return result.scalar_one_or_none()


async def orm_get_user_by_db_id(session: AsyncSession, user_db_id: int):
    result = await session.execute(select(User).where(User.id == user_db_id))
    return result.scalar_one_or_none()


async def orm_get_or_create_active_batch_code(session: AsyncSession, telegram_user_id: int) -> str:
    user = await orm_get_user(session, telegram_user_id)
    if user is None:
        raise ValueError("User is not registered")

    if not user.active_batch_code:
        user.active_batch_code = uuid4().hex[:12]
        await session.commit()
        await session.refresh(user)

    return user.active_batch_code


async def orm_save_user_address(
    session: AsyncSession,
    *,
    user_db_id: int,
    address: str,
    delivery_lat: float | None = None,
    delivery_lon: float | None = None,
    pickup_point: str | None = None,
):
    await session.execute(
        update(SavedAddress)
        .where(SavedAddress.user_id == user_db_id)
        .values(is_default=False)
    )

    result = await session.execute(
        select(SavedAddress).where(
            SavedAddress.user_id == user_db_id,
            SavedAddress.address == address,
            SavedAddress.pickup_point == pickup_point,
        )
    )
    saved_address = result.scalar_one_or_none()

    if saved_address is None:
        saved_address = SavedAddress(
            user_id=user_db_id,
            address=address,
            delivery_lat=delivery_lat,
            delivery_lon=delivery_lon,
            pickup_point=pickup_point,
            is_default=True,
        )
        session.add(saved_address)
    else:
        saved_address.delivery_lat = delivery_lat
        saved_address.delivery_lon = delivery_lon
        saved_address.pickup_point = pickup_point
        saved_address.is_default = True


async def orm_update_user_delivery_profile(
    session: AsyncSession,
    telegram_user_id: int,
    *,
    phone: str | None = None,
    delivery_address: str | None = None,
    delivery_lat: float | None = None,
    delivery_lon: float | None = None,
    pickup_point: str | None = None,
):
    user = await orm_get_user(session, telegram_user_id)
    if user is None:
        raise ValueError("User is not registered")

    if phone:
        user.phone = phone
    if delivery_address is not None:
        user.default_delivery_address = delivery_address
    if delivery_lat is not None:
        user.default_delivery_lat = float(delivery_lat)
    if delivery_lon is not None:
        user.default_delivery_lon = float(delivery_lon)
    user.default_pickup_point = pickup_point

    if delivery_address:
        await orm_save_user_address(
            session,
            user_db_id=user.id,
            address=delivery_address,
            delivery_lat=delivery_lat,
            delivery_lon=delivery_lon,
            pickup_point=pickup_point,
        )

    await session.commit()
    await session.refresh(user)
    return user


async def orm_get_user_saved_addresses(session: AsyncSession, telegram_user_id: int, limit: int = 5):
    user = await orm_get_user(session, telegram_user_id)
    if user is None:
        return []

    result = await session.execute(
        select(SavedAddress)
        .where(SavedAddress.user_id == user.id)
        .order_by(SavedAddress.is_default.desc(), SavedAddress.updated.desc(), SavedAddress.id.desc())
        .limit(limit)
    )
    return result.scalars().all()


async def orm_get_user_saved_address(session: AsyncSession, telegram_user_id: int, address_id: int):
    user = await orm_get_user(session, telegram_user_id)
    if user is None:
        return None

    result = await session.execute(
        select(SavedAddress).where(
            SavedAddress.id == address_id,
            SavedAddress.user_id == user.id,
        )
    )
    return result.scalar_one_or_none()


async def orm_create_order(
    session: AsyncSession,
    telegram_user_id: int,
    data: dict,
    *,
    status: str = "new",
    batch_code: str | None = None,
):
    user = await orm_get_user(session, telegram_user_id)
    if user is None:
        raise ValueError("User is not registered")

    pricing = data.get("pricing") or calculate_order_totals(float(data.get("price", 0) or 0))
    order = Order(
        user_id=user.id,
        item_id=data.get("item_id"),
        batch_code=batch_code,
        product_name=data["product_name"],
        size=data["size"],
        price=pricing["price"],
        service_fee=pricing["service_fee"],
        delivery_fee=pricing["delivery_fee"],
        total_price=pricing["total_price"],
        phone=data["phone"],
        delivery_address=data.get("delivery_address"),
        delivery_lat=data.get("delivery_lat"),
        delivery_lon=data.get("delivery_lon"),
        nearest_pickup_point=data.get("nearest_pickup_point"),
        source_platform=data.get("source_platform"),
        source_url=data.get("source_url"),
        comment=data.get("comment"),
        status=status,
    )
    session.add(order)
    await session.commit()
    await session.refresh(order)
    return order


async def orm_add_order_to_active_batch(session: AsyncSession, telegram_user_id: int, data: dict):
    batch_code = await orm_get_or_create_active_batch_code(session, telegram_user_id)
    order = await orm_create_order(
        session,
        telegram_user_id,
        data,
        status="draft",
        batch_code=batch_code,
    )
    return order, batch_code


async def orm_get_user_active_batch_orders(session: AsyncSession, telegram_user_id: int):
    user = await orm_get_user(session, telegram_user_id)
    if user is None or not user.active_batch_code:
        return []

    result = await session.execute(
        select(Order)
        .where(
            Order.user_id == user.id,
            Order.batch_code == user.active_batch_code,
            Order.status == "draft",
        )
        .order_by(Order.created.asc(), Order.id.asc())
    )
    return result.scalars().all()


async def orm_get_orders_by_batch_code(session: AsyncSession, batch_code: str):
    result = await session.execute(
        select(Order).where(Order.batch_code == batch_code).order_by(Order.created.asc(), Order.id.asc())
    )
    return result.scalars().all()


async def orm_finalize_active_batch(session: AsyncSession, telegram_user_id: int):
    user = await orm_get_user(session, telegram_user_id)
    if user is None or not user.active_batch_code:
        return [], None

    orders = await orm_get_user_active_batch_orders(session, telegram_user_id)
    if not orders:
        user.active_batch_code = None
        await session.commit()
        return [], None

    batch_code = user.active_batch_code
    for order in orders:
        order.status = "new"

    user.active_batch_code = None
    await session.commit()

    refreshed_orders = await orm_get_orders_by_batch_code(session, batch_code)
    return refreshed_orders, batch_code


async def orm_cancel_active_batch(session: AsyncSession, telegram_user_id: int) -> int:
    user = await orm_get_user(session, telegram_user_id)
    if user is None or not user.active_batch_code:
        return 0

    draft_orders = await orm_get_user_active_batch_orders(session, telegram_user_id)
    if draft_orders:
        await session.execute(
            delete(Order).where(
                Order.user_id == user.id,
                Order.batch_code == user.active_batch_code,
                Order.status == "draft",
            )
        )

    user.active_batch_code = None
    await session.commit()
    return len(draft_orders)


async def orm_get_user_orders(session: AsyncSession, telegram_user_id: int):
    user = await orm_get_user(session, telegram_user_id)
    if user is None:
        return []

    result = await session.execute(
        select(Order)
        .where(Order.user_id == user.id, Order.status != "draft")
        .order_by(Order.created.desc(), Order.id.desc())
    )
    return result.scalars().all()


async def orm_get_user_order(session: AsyncSession, telegram_user_id: int, order_id: int):
    user = await orm_get_user(session, telegram_user_id)
    if user is None:
        return None

    result = await session.execute(
        select(Order).where(
            Order.id == order_id,
            Order.user_id == user.id,
            Order.status != "draft",
        )
    )
    return result.scalar_one_or_none()


async def orm_get_orders(session: AsyncSession):
    result = await session.execute(
        select(Order)
        .where(Order.status != "draft")
        .order_by(Order.created.desc(), Order.id.desc())
    )
    return result.scalars().all()


async def orm_get_order(session: AsyncSession, order_id: int):
    result = await session.execute(select(Order).where(Order.id == order_id))
    return result.scalar_one_or_none()


async def orm_update_order_status(session: AsyncSession, order_id: int, status: str):
    await session.execute(update(Order).where(Order.id == order_id).values(status=status))
    await session.commit()


async def orm_delete_order(session: AsyncSession, order_id: int) -> bool:
    result = await session.execute(delete(Order).where(Order.id == order_id))
    await session.commit()
    return bool(result.rowcount)


async def orm_get_clients(session: AsyncSession, limit: int = 20):
    result = await session.execute(
        select(User)
        .join(Order, Order.user_id == User.id)
        .group_by(User.id)
        .order_by(func.max(Order.created).desc())
        .limit(limit)
    )
    return result.scalars().all()


async def orm_get_client_profile(session: AsyncSession, user_db_id: int):
    user = await orm_get_user_by_db_id(session, user_db_id)
    if user is None:
        return None

    addresses_result = await session.execute(
        select(SavedAddress)
        .where(SavedAddress.user_id == user.id)
        .order_by(SavedAddress.is_default.desc(), SavedAddress.updated.desc())
        .limit(5)
    )
    orders_result = await session.execute(
        select(Order)
        .where(Order.user_id == user.id, Order.status != "draft")
        .order_by(Order.created.desc(), Order.id.desc())
        .limit(10)
    )
    addresses = addresses_result.scalars().all()
    orders = orders_result.scalars().all()
    return {
        "user": user,
        "addresses": addresses,
        "orders": orders,
    }


async def orm_is_admin(session: AsyncSession, user_id: int) -> bool:
    result = await session.execute(select(ChatAdmin.id).where(ChatAdmin.user_id == user_id))
    return result.first() is not None


async def orm_sync_chat_admins(session: AsyncSession, chat_id: int, admin_user_ids: set[int]):
    result = await session.execute(select(ChatAdmin).where(ChatAdmin.chat_id == chat_id))
    existing_records = result.scalars().all()
    existing_ids = {record.user_id for record in existing_records}

    ids_to_add = admin_user_ids - existing_ids
    ids_to_remove = existing_ids - admin_user_ids

    if ids_to_add:
        session.add_all([ChatAdmin(chat_id=chat_id, user_id=user_id) for user_id in ids_to_add])

    if ids_to_remove:
        await session.execute(
            delete(ChatAdmin).where(
                ChatAdmin.chat_id == chat_id,
                ChatAdmin.user_id.in_(ids_to_remove),
            )
        )

    await session.commit()


async def orm_get_admin_ids(session: AsyncSession):
    result = await session.execute(select(ChatAdmin.user_id).distinct())
    return set(result.scalars().all())
