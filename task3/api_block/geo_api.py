import aiohttp
import asyncio
from config_reader import config

USER_AGENT = "MyTelegramBot/1.0 (zotova.sp@inbox.ru)"  #обязательно для Wikipedia

# ищем координаты по адресу через 2gis
async def search_locations_2gis(query, session):
    url = "https://catalog.api.2gis.com/3.0/items"
    params = {
        "q": query,
        "fields": "items.point",
        "key": config.gis_token.get_secret_value(),
        "page_size": 5
    }
    async with session.get(url, params=params) as resp:
        data = await resp.json()
    items = data.get("result", {}).get("items", [])
    result = []
    for item in items:
        name = item.get("name", item.get("address_name", "Адрес"))
        point = item.get("point", {})
        lat = point.get("lat")
        lon = point.get("lon")
        if lat is not None and lon is not None:
            result.append({
                "name": name,
                "lat": lat,
                "lon": lon
            })
    return result

# запрос погоды через OpenMeteo
async def get_open_meteo_weather(lat, lon, session):
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "current_weather": "true",
    }
    async with session.get(url, params=params) as resp:
        js = await resp.json()
    if "current_weather" not in js:
        return "Погода не найдена"
    w = js["current_weather"]
    return (
        f"Температура: {w['temperature']}°C\n"
        f"Ветер: {w['windspeed']} м/с"
    )

# через Wiki GeoData поиск точек рядом
async def get_nearby_places(lat, lon, session):
    url = "https://ru.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "list": "geosearch",
        "gscoord": f"{lat}|{lon}",
        "gsradius": 1000,
        "gslimit": 5,
        "format": "json"
    }
    headers = {"User-Agent": USER_AGENT}
    async with session.get(url, params=params, headers=headers) as resp:
        data = await resp.json()
    result = []
    for place in data.get("query", {}).get("geosearch", []):
        result.append({"pageid": place["pageid"], "title": place["title"]})
    return result

# через Wiki TextExtracts описание точек по pageid
async def get_wiki_extract(pageid, session):
    url = "https://ru.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "prop": "extracts",
        "exintro": "true",
        "explaintext": "true",
        "format": "json",
        "pageids": pageid
    }
    headers = {"User-Agent": USER_AGENT}
    async with session.get(url, params=params, headers=headers) as resp:
        data = await resp.json()
    page = next(iter(data.get("query", {}).get("pages", {}).values()), {})
    extract = page.get("extract", "")
    return extract.strip()

# Wikipedia pageid по названию для самого места
async def get_wiki_pageid_by_title(title, session):
    url = "https://ru.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "format": "json",
        "titles": title
    }
    headers = {"User-Agent": USER_AGENT}
    async with session.get(url, params=params, headers=headers) as resp:
        data = await resp.json()
    pages = data.get("query", {}).get("pages", {})
    for pageid, pageinfo in pages.items():
        if pageid != "-1":
            return int(pageid)
    return None

# Wikipedia список интересных точек с описаниями, получаем выгрузку списка+описание
async def get_places_with_descriptions(lat, lon, session):
    places = await get_nearby_places(lat, lon, session)
    if not places:
        return "Нет интересных мест поблизости."
    tasks = [get_wiki_extract(place["pageid"], session) for place in places]
    extracts = await asyncio.gather(*tasks)
    out = []
    for place, descr in zip(places, extracts):
        intro = descr if descr else "нет описания"
        out.append(f"• {place['title']}:\n{intro}")
    return "\n\n".join(out)
