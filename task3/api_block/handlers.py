import asyncio
import aiohttp
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, KeyboardButton, ReplyKeyboardMarkup
from api_block.geo_api import (
    search_locations_2gis,
    get_open_meteo_weather,
    get_places_with_descriptions,
    get_nearby_places,
    get_wiki_extract,
    get_wiki_pageid_by_title
)

MAX_LENGTH = 4096
router = Router()

@router.message(Command("start"))
async def start_command(message: Message):
    await message.answer("Введите адрес, место или город:")

@router.message()
async def universal_handler(message: Message):
    text = message.text.strip()
    # если пользователь выбрал место с кнопки (есть "[")
    if "[" in text and "]" in text:
        try:
            raw = text.split("[")[1].split("]")[0]
            lat, lon = map(float, raw.split(","))
        except Exception:
            await message.answer("Ошибка: не удалось разобрать координаты.")
            return

        # сохраняем имя выбранного места из кнопки
        selected_name = text.split("[")[0].strip()

        async with aiohttp.ClientSession() as session:
            # готовим все основные корутины параллельно: погода, интересные места, список интересных мест, pageid по имени
            weather_task = get_open_meteo_weather(lat, lon, session)
            places_task = get_places_with_descriptions(lat, lon, session)
            short_places_task = get_nearby_places(lat, lon, session)
            pageid_task = get_wiki_pageid_by_title(selected_name, session)
            weather, places, short_places, pageid = await asyncio.gather(
                weather_task, places_task, short_places_task, pageid_task
            )

            if pageid:
                main_descr = await get_wiki_extract(pageid, session)
            else:
                main_descr = None

            # формируем основной текст
            base = (
                f"Координаты: {lat:.5f}, {lon:.5f}\n{weather}\n\n"
                f"Описание места «{selected_name}»:\n{main_descr if main_descr else 'Нет описания.'}\n\n"
            )
            answer = base + f"Интересные места поблизости:\n{places}"

            if len(answer) > MAX_LENGTH:
                # если слишком длинный текст, то только названия интересных мест, описание основного места всегда остается
                places_names = [f"• {place['title']}" for place in short_places]
                short_answer = (
                        base +
                        f"Интересные места поблизости:\n" +
                        "\n".join(places_names) +
                        "\n\nОписание мест поблизости не выведено: сообщение слишком длинное."
                )
                await message.answer(short_answer)
            else:
                await message.answer(answer)
    else:
        async with aiohttp.ClientSession() as session:
            results = await search_locations_2gis(text, session)
            if not results:
                await message.answer("Не удалось найти вариантов локации. Попробуйте другой адрес.")
                return
            kb = [
                [KeyboardButton(text=f"{item['name']} [{item['lat']},{item['lon']}]")]
                for item in results
            ]
            reply = ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
            await message.answer("Выберите одну из локаций:", reply_markup=reply)
