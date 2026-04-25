import os
import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiohttp import web
from dotenv import load_dotenv
from deep_translator import GoogleTranslator
from langdetect import DetectorFactory, LangDetectException, detect

load_dotenv()
token = os.getenv("BOT_TOKEN")
if not token:
    raise ValueError("Переменная BOT_TOKEN не задана в .env")

bot = Bot(token=token)
dp = Dispatcher()
DetectorFactory.seed = 0
discussion_chat_ids_raw = os.getenv("DISCUSSION_CHAT_IDS", "")
discussion_chat_ids: set[int] = set()
for value in discussion_chat_ids_raw.split(","):
    value = value.strip()
    if value:
        discussion_chat_ids.add(int(value))

# Обратная совместимость со старой переменной для одного чата.
single_chat_id_raw = os.getenv("DISCUSSION_CHAT_ID")
if single_chat_id_raw:
    for value in single_chat_id_raw.split(","):
        value = value.strip()
        if value:
            discussion_chat_ids.add(int(value))

bot_id: int | None = None
webhook_host = os.getenv("WEBHOOK_HOST", "").strip()
webhook_path = os.getenv("WEBHOOK_PATH", "/webhook").strip() or "/webhook"
webhook_secret = os.getenv("WEBHOOK_SECRET", "").strip() or None


def is_probably_russian(text: str) -> bool:
    cyrillic = sum(1 for char in text if "а" <= char.lower() <= "я" or char.lower() == "ё")
    latin = sum(1 for char in text if "a" <= char.lower() <= "z")
    return cyrillic > 0 and latin == 0


async def translate_foreign_to_ru(text: str) -> tuple[str | None, str]:
    normalized = text.strip()
    if not normalized:
        return None, "unknown"

    if is_probably_russian(normalized):
        return None, "ru"

    try:
        source_lang = await asyncio.to_thread(detect, normalized)
    except LangDetectException:
        source_lang = "unknown"

    if source_lang == "ru":
        return None, source_lang

    translated_text = await asyncio.to_thread(GoogleTranslator(source="auto", target="ru").translate, normalized)
    translated_text = translated_text.strip() if translated_text else ""
    if not translated_text:
        return None, source_lang

    # Если перевод совпал с исходным текстом, считаем, что перевод не нужен.
    if translated_text.casefold() == normalized.casefold():
        return None, source_lang

    return translated_text, source_lang

@dp.message(F.text)
async def handle_message(message: Message):
    if message.chat.type not in {"group", "supergroup"}:
        return

    if discussion_chat_ids and message.chat.id not in discussion_chat_ids:
        return

    if bot_id is not None and message.from_user and message.from_user.id == bot_id:
        return

    if not message.text or message.text.startswith("/"):
        return

    try:
        translated, source_lang = await translate_foreign_to_ru(message.text)
        if not translated:
            return
        await message.reply(f"Перевод ({source_lang} -> ru):\n{translated}")
    except Exception as error:
        print(f"Ошибка перевода: {error!r}")
        try:
            await message.reply("Не удалось выполнить перевод (ошибка сервиса).")
        except Exception:
            pass


async def health_handler(_: web.Request) -> web.Response:
    return web.Response(text="ok")


async def webhook_handler(request: web.Request) -> web.Response:
    if webhook_secret:
        incoming_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if incoming_secret != webhook_secret:
            return web.Response(status=403, text="forbidden")

    update_data = await request.json()
    await dp.feed_raw_update(bot=bot, update=update_data)
    return web.Response(text="ok")


async def run_webhook_server(port: int) -> None:
    app = web.Application()
    app.router.add_get("/", health_handler)
    app.router.add_get("/healthz", health_handler)
    app.router.add_post(webhook_path, webhook_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    print(f"webhook server started on 0.0.0.0:{port}; path={webhook_path}")

    # Держим процесс живым.
    while True:
        await asyncio.sleep(3600)

async def main():
    global bot_id
    me = await bot.get_me()
    bot_id = me.id
    print(f"bot started: @{me.username} (id={bot_id})")

    if webhook_host:
        port = int(os.getenv("PORT", "10000"))
        webhook_url = f"{webhook_host.rstrip('/')}{webhook_path}"
        await bot.set_webhook(
            url=webhook_url,
            drop_pending_updates=True,
            secret_token=webhook_secret,
        )
        print(f"webhook set: {webhook_url}")
        await run_webhook_server(port)
        return

    print("WEBHOOK_HOST not set, fallback to polling mode")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
