"""
Отдельный процесс бота (не веб-сервер!). Слушает команду /start и отвечает
приветствием с кнопкой, открывающей Mini App.

Запуск:
    python bot.py

Нужны переменные окружения (те же, что в .env для backend):
    BOT_TOKEN    — токен от @BotFather
    WEBAPP_URL   — https-адрес вашего Mini App (тот же, что в Menu Button)
"""
import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBAPP_URL = os.environ["WEBAPP_URL"]

WELCOME_TEXT = (
    "Привет, {name}! 👋\n\n"
    "Это твой личный трекер портфеля для ребалансировки активов.\n\n"
    "Как это работает: ты вносишь депозит, распределяешь его по активам с "
    "целевыми долями в процентах, а бот сам следит за ценами. Если актив "
    "вырастает выше target — подскажет, сколько продать. Если падает ниже — "
    "подскажет, сколько докупить на свободный USDT. Плюс считает твою прибыль.\n\n"
    "Жми на кнопку «Портфель» 👇"
)

bot = Bot(BOT_TOKEN)
dp = Dispatcher()


@dp.message(CommandStart())
async def start_handler(message: Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Портфель", web_app=WebAppInfo(url=WEBAPP_URL))
    ]])
    name = message.from_user.first_name or "друг"
    await message.answer(WELCOME_TEXT.format(name=name), reply_markup=keyboard)


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
