import asyncio
import logging
import os
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("fresh_bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
PORT = int(os.getenv("PORT", "10000"))


async def index(request: web.Request):
    return web.Response(text="Serveur en ligne", content_type="text/plain")


async def run_bot():
    if not BOT_TOKEN:
        log.error("BOT_TOKEN est vide : ajoute BOT_TOKEN dans Environment sur Render.")
        return

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    @dp.message(CommandStart())
    async def on_start(message: Message):
        name = message.from_user.first_name if message.from_user else "frère"
        await message.answer(f"Salut {name} ! Le nouveau bot fonctionne bien.")

    await dp.start_polling(bot)


async def main():
    app = web.Application()
    app.router.add_get("/", index)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

    await run_bot()


if __name__ == "__main__":
    asyncio.run(main())
