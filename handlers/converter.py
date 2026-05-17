import os
import time

from aiohttp import ClientSession
from dotenv import find_dotenv, load_dotenv


load_dotenv(find_dotenv())


CURRENCY_ALIASES = {
    "cny": "CNY",
    "yuan": "CNY",
    "юань": "CNY",
    "юани": "CNY",
    "eur": "EUR",
    "euro": "EUR",
    "евро": "EUR",
    "usd": "USD",
    "dollar": "USD",
    "dollars": "USD",
    "доллар": "USD",
    "доллары": "USD",
    "rub": "RUB",
    "ruble": "RUB",
    "rubles": "RUB",
    "руб": "RUB",
    "рубль": "RUB",
    "рубли": "RUB",
}
DEFAULT_MARKUP_FACTOR = float(os.getenv("CONVERTER_MARKUP_FACTOR", "1.04"))
RUSSIA_DELIVERY_FEE_RUB = float(os.getenv("RUSSIA_DELIVERY_FEE_RUB", "1000"))
_RATES_CACHE: dict[str, float] = {}
_RATES_CACHE_TS = 0.0
_RATES_CACHE_TTL = int(os.getenv("RATES_CACHE_TTL_SECONDS", "1800"))


def normalize_currency(currency: str) -> str:
    normalized = (currency or "").strip().lower()
    if normalized not in CURRENCY_ALIASES:
        raise ValueError(f"Unsupported currency: {currency}")
    return CURRENCY_ALIASES[normalized]


async def _get_usd_rates(session: ClientSession) -> dict[str, float]:
    global _RATES_CACHE_TS

    if _RATES_CACHE and (time.time() - _RATES_CACHE_TS) < _RATES_CACHE_TTL:
        return _RATES_CACHE

    api_key = os.getenv("API_KEY")
    async with session.get(
        f"https://openexchangerates.org/api/latest.json?app_id={api_key}&symbols=RUB,CNY,EUR,USD"
    ) as response:
        payload = await response.json()

    rates = payload.get("rates", {})
    if "RUB" not in rates:
        raise ValueError("RUB exchange rate is unavailable")

    _RATES_CACHE.clear()
    _RATES_CACHE.update({code.upper(): float(value) for code, value in rates.items()})
    _RATES_CACHE["USD"] = 1.0
    _RATES_CACHE_TS = time.time()
    return _RATES_CACHE


async def get_rate_to_rub(session: ClientSession, currency: str) -> float:
    normalized = normalize_currency(currency)
    if normalized == "RUB":
        return 1.0

    rates = await _get_usd_rates(session)
    if normalized not in rates:
        raise ValueError(f"Exchange rate for {normalized} is unavailable")

    return round(rates["RUB"] / rates[normalized], 4)


async def calculate_total_in_rub(
    session: ClientSession,
    cost: float | int,
    currency: str,
    markup_factor: float = DEFAULT_MARKUP_FACTOR,
) -> dict[str, float | str]:
    amount = float(cost)
    rate_to_rub = await get_rate_to_rub(session, currency)
    subtotal_rub = round(amount * rate_to_rub, 2)
    total_rub = round(subtotal_rub * markup_factor, 2)
    return {
        "currency": normalize_currency(currency),
        "amount": amount,
        "rate_to_rub": rate_to_rub,
        "subtotal_rub": subtotal_rub,
        "markup_factor": markup_factor,
        "total_rub": total_rub,
    }


async def calculate_order_pricing(
    session: ClientSession,
    cost: float | int,
    currency: str,
    markup_factor: float = DEFAULT_MARKUP_FACTOR,
    delivery_fee_rub: float = RUSSIA_DELIVERY_FEE_RUB,
) -> dict[str, float | str]:
    result = await calculate_total_in_rub(
        session=session,
        cost=cost,
        currency=currency,
        markup_factor=markup_factor,
    )
    service_fee = round(result["total_rub"] - result["subtotal_rub"], 2)
    delivery_fee = round(float(delivery_fee_rub), 2)
    total_price = round(result["total_rub"] + delivery_fee, 2)
    return {
        **result,
        "price": result["subtotal_rub"],
        "service_fee": service_fee,
        "delivery_fee": delivery_fee,
        "total_price": total_price,
    }


async def converter_rate(session: ClientSession, cost, currency):
    result = await calculate_order_pricing(session, cost, currency)
    return (
        f"Курс на сегодня: {result['rate_to_rub']} руб.\n"
        f"Стоимость товара в рублях: {result['price']} руб.\n"
        f"Комиссия и доставка до Москвы: {result['service_fee']} руб.\n"
        f"Доставка по России: {result['delivery_fee']} руб.\n"
        f"Итоговая стоимость: {result['total_price']} руб."
    )
