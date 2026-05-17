import os


DEFAULT_MARKUP_FACTOR = float(os.getenv("CONVERTER_MARKUP_FACTOR", "1.04"))
RUSSIA_DELIVERY_FEE_RUB = float(os.getenv("RUSSIA_DELIVERY_FEE_RUB", "1000"))


def calculate_order_totals(price: float | int) -> dict[str, float]:
    subtotal = round(float(price or 0), 2)
    if subtotal <= 0:
        return {
            "price": 0.0,
            "service_fee": 0.0,
            "delivery_fee": 0.0,
            "total_price": 0.0,
        }

    service_fee = round(subtotal * (DEFAULT_MARKUP_FACTOR - 1), 2)
    delivery_fee = round(RUSSIA_DELIVERY_FEE_RUB, 2)
    total_price = round(subtotal + service_fee + delivery_fee, 2)
    return {
        "price": subtotal,
        "service_fee": service_fee,
        "delivery_fee": delivery_fee,
        "total_price": total_price,
    }


def summarize_order_totals(orders: list) -> dict[str, float | int]:
    known_orders = [order for order in orders if float(getattr(order, "total_price", 0) or 0) > 0]
    unknown_count = len(orders) - len(known_orders)

    subtotal = round(sum(float(order.price) for order in known_orders), 2)
    service_fee = round(sum(float(order.service_fee) for order in known_orders), 2)
    delivery_fee = round(sum(float(order.delivery_fee) for order in known_orders), 2)
    total_price = round(sum(float(order.total_price) for order in known_orders), 2)

    return {
        "known_count": len(known_orders),
        "unknown_count": unknown_count,
        "subtotal": subtotal,
        "service_fee": service_fee,
        "delivery_fee": delivery_fee,
        "total_price": total_price,
    }
