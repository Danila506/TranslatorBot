import os
import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
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
        print("skip: not group/supergroup")
        return

    print("chat_id:", message.chat.id, "type:", message.chat.type, "title:", message.chat.title)
    if discussion_chat_ids and message.chat.id not in discussion_chat_ids:
        print(f"skip: chat not allowed ({message.chat.id})")
        return

    if bot_id is not None and message.from_user and message.from_user.id == bot_id:
        print("skip: message from this bot")
        return

    if not message.text or message.text.startswith("/"):
        print(f"skip: empty or command text={message.text!r}")
        return

    try:
        print("translate: start")
        translated, source_lang = await translate_foreign_to_ru(message.text)
        print(f"source_lang={source_lang}; text={message.text!r}; translated={translated!r}")
        if not translated:
            print("skip: no translated text")
            return
        await message.reply(f"Перевод ({source_lang} -> ru):\n{translated}")
        print("translate: reply sent")
    except Exception as error:
        print(f"Ошибка перевода: {error!r}")
        await message.reply("Не удалось выполнить перевод (ошибка сервиса).")

async def main():
    global bot_id
    me = await bot.get_me()
    bot_id = me.id
    print(f"bot started: @{me.username} (id={bot_id})")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
