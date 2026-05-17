import json
from dataclasses import dataclass
from functools import lru_cache
from math import asin, cos, radians, sin, sqrt
from pathlib import Path


OFFICES_JSON_PATH = Path(__file__).resolve().parent.parent / "common" / "cdek_offices.json"


@dataclass(slots=True)
class LocalPickupPoint:
    point_type: str
    city: str
    address: str
    office_number: str | None
    comment: str | None
    latitude: float
    longitude: float


@dataclass(slots=True)
class LocalPickupDistance:
    point: LocalPickupPoint
    distance_km: float


def _haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_km = 6371.0
    lat1_rad, lon1_rad = radians(lat1), radians(lon1)
    lat2_rad, lon2_rad = radians(lat2), radians(lon2)
    delta_lat = lat2_rad - lat1_rad
    delta_lon = lon2_rad - lon1_rad

    a = sin(delta_lat / 2) ** 2 + cos(lat1_rad) * cos(lat2_rad) * sin(delta_lon / 2) ** 2
    c = 2 * asin(sqrt(a))
    return earth_radius_km * c


@lru_cache(maxsize=1)
def _load_points() -> tuple[LocalPickupPoint, ...]:
    with OFFICES_JSON_PATH.open("r", encoding="utf-8-sig") as file:
        raw_items = json.load(file)

    points = []
    for item in raw_items:
        try:
            points.append(
                LocalPickupPoint(
                    point_type=str(item.get("type") or "").strip(),
                    city=str(item.get("city") or "").strip(),
                    address=str(item.get("address") or "").strip(),
                    office_number=str(item.get("office_number") or "").strip() or None,
                    comment=str(item.get("comment") or "").strip() or None,
                    latitude=float(item["latitude"]),
                    longitude=float(item["longitude"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue

    return tuple(points)


def _filter_points_by_city(points: tuple[LocalPickupPoint, ...], city: str | None) -> list[LocalPickupPoint]:
    if not city:
        return list(points)

    lowered_city = city.casefold()
    city_points = [point for point in points if point.city.casefold() == lowered_city]
    return city_points or list(points)


def _filter_points_by_type(
    points: list[LocalPickupPoint],
    office_types: tuple[str, ...] | None,
) -> list[LocalPickupPoint]:
    if not office_types:
        return points

    normalized_types = {office_type.casefold() for office_type in office_types}
    filtered = [point for point in points if point.point_type.casefold() in normalized_types]
    return filtered or points


def find_nearest_pickup_points(
    *,
    latitude: float,
    longitude: float,
    city: str | None = None,
    limit: int = 3,
    max_distance_km: float = 80.0,
    office_types: tuple[str, ...] | None = None,
) -> list[LocalPickupDistance]:
    points = _filter_points_by_city(_load_points(), city)
    points = _filter_points_by_type(points, office_types)

    distances = [
        LocalPickupDistance(
            point=point,
            distance_km=_haversine_distance_km(latitude, longitude, point.latitude, point.longitude),
        )
        for point in points
    ]
    distances.sort(key=lambda item: item.distance_km)

    limited = distances[:limit]
    if limited and limited[0].distance_km <= max_distance_km:
        return limited
    return []


def format_pickup_option(item: LocalPickupDistance, index: int | None = None) -> str:
    office_label = item.point.point_type or "Пункт"
    extra = f" | {item.point.comment}" if item.point.comment else ""
    prefix = f"{index}. " if index is not None else ""
    return (
        f"{prefix}{office_label}, {item.point.address} "
        f"(~ {round(item.distance_km, 1)} км){extra}"
    )


def format_pickup_options(points: list[LocalPickupDistance]) -> str | None:
    if not points:
        return None

    return "\n".join(
        format_pickup_option(item, index=index)
        for index, item in enumerate(points, start=1)
    )
