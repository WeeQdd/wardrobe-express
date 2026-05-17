import asyncio
import json
import os
from dataclasses import dataclass
from urllib.parse import urlencode
from xml.etree import ElementTree

from aiohttp import ClientError, ClientSession


YANDEX_GEOCODER_URL = "https://geocode-maps.yandex.ru/v1"
YANDEX_GEOCODER_TIMEOUT = int(os.getenv("YANDEX_GEOCODER_TIMEOUT_SECONDS", "10"))


class YandexGeocoderError(Exception):
    pass


@dataclass(slots=True)
class GeocodedAddress:
    formatted_address: str
    latitude: float
    longitude: float
    city: str | None = None
    postal_code: str | None = None
    country_code: str | None = None


def _get_api_key() -> str | None:
    return os.getenv("YANDEX_GEOCODER_API_KEY")


def _extract_first_member(data: dict) -> dict | None:
    members = (
        data.get("response", {})
        .get("GeoObjectCollection", {})
        .get("featureMember", [])
    )
    if not members:
        return None
    return members[0].get("GeoObject")


def _extract_address_components(meta: dict) -> tuple[str | None, str | None, str | None]:
    address_data = meta.get("Address", {})
    components = address_data.get("Components", [])

    city = None
    postal_code = address_data.get("postal_code")
    country_code = address_data.get("country_code")

    for component in components:
        kind = component.get("kind")
        name = component.get("name")
        if kind in {"locality", "province"} and not city:
            city = name
        if kind == "postal_code" and not postal_code:
            postal_code = name
        if kind == "country" and not country_code:
            country_code = component.get("code") or country_code

    return city, postal_code, country_code


def _parse_geo_object(geo_object: dict) -> GeocodedAddress:
    meta = geo_object.get("metaDataProperty", {}).get("GeocoderMetaData", {})
    address = meta.get("Address", {}).get("formatted") or meta.get("text") or "Адрес не определен"
    pos = geo_object.get("Point", {}).get("pos", "")
    lon_str, lat_str = pos.split()
    city, postal_code, country_code = _extract_address_components(meta)
    return GeocodedAddress(
        formatted_address=address,
        latitude=float(lat_str),
        longitude=float(lon_str),
        city=city,
        postal_code=postal_code,
        country_code=country_code,
    )


def _load_json_response(text: str) -> dict:
    stripped = text.strip()
    if not stripped:
        raise YandexGeocoderError("Yandex Geocoder вернул пустой ответ.")

    if stripped.startswith("<?xml") or stripped.startswith("<error"):
        try:
            root = ElementTree.fromstring(stripped)
            message = root.findtext(".//message")
            error = root.findtext(".//error")
        except ElementTree.ParseError:
            message = None
            error = None

        details = message or error or "Yandex Geocoder вернул XML-ошибку."
        raise YandexGeocoderError(details)

    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        preview = stripped[:200].replace("\n", " ")
        raise YandexGeocoderError(
            f"Yandex Geocoder вернул не-JSON ответ: {preview}"
        ) from None

    if not isinstance(data, dict):
        raise YandexGeocoderError("Yandex Geocoder вернул неожиданный формат ответа.")

    return data


async def _request_geocoder(session: ClientSession, query: str, *, kind: str | None = None) -> GeocodedAddress:
    api_key = _get_api_key()
    if not api_key:
        raise YandexGeocoderError("Не задан YANDEX_GEOCODER_API_KEY.")

    params = {
        "apikey": api_key,
        "geocode": query,
        "lang": "ru_RU",
        "format": "json",
        "results": 1,
    }
    if kind:
        params["kind"] = kind

    url = f"{YANDEX_GEOCODER_URL}?{urlencode(params)}"
    try:
        async with session.get(url, timeout=YANDEX_GEOCODER_TIMEOUT) as response:
            response_text = await response.text()
            data = _load_json_response(response_text)
            if response.status >= 400:
                message = data.get("message") if isinstance(data, dict) else None
                raise YandexGeocoderError(message or f"Yandex Geocoder error: {response.status}")
    except asyncio.TimeoutError:
        raise YandexGeocoderError("Сервис геокодирования Яндекса не ответил вовремя. Попробуйте еще раз позже.") from None
    except ClientError:
        raise YandexGeocoderError("Не удалось подключиться к сервису геокодирования Яндекса.") from None

    geo_object = _extract_first_member(data)
    if not geo_object:
        raise YandexGeocoderError("Адрес не найден.")

    return _parse_geo_object(geo_object)


async def geocode_address(session: ClientSession, address: str) -> GeocodedAddress:
    return await _request_geocoder(session, address)


async def reverse_geocode(session: ClientSession, latitude: float, longitude: float) -> GeocodedAddress:
    query = f"{longitude},{latitude}"
    return await _request_geocoder(session, query, kind="house")
