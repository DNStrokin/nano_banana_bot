import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from config import config
from database import init_db
from nano_service import nano_service

# Configure logging
logging.basicConfig(level=logging.INFO)

# Initialize Bot and Dispatcher
bot = Bot(token=config.BOT_TOKEN.get_secret_value())
dp = Dispatcher()

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer(f"Привет, {message.from_user.full_name}! Я Nano Banana Bot. 🍌\nСкоро здесь будет магия генерации изображений.")

@dp.message(Command("generate"))
async def cmd_generate(message: types.Message):
    # Determine model from arguments: /generate pro, /generate imagen, /generate simple
    args = message.text.split(maxsplit=1)
    prompt = "Test Prompt"
    model = "nano_banana_pro"
    
    if len(args) > 1:
        # Simple arg parsing for testing
        if "imagen" in args[1].lower():
            model = "imagen"
        elif "simple" in args[1].lower() or "flash" in args[1].lower():
            model = "nano_banana"
    
    await message.answer(f"🍌 Начинаю генерацию ({model})...")
    try:
        image_bytes = await nano_service.generate_image("Modern cityscape with bananas", model_type=model)
        from aiogram.types import BufferedInputFile
        photo = BufferedInputFile(image_bytes, filename=f"banana_{model}.png")
        await message.answer_photo(photo, caption=f"Вот ваше изображение ({model})!")
    except Exception as e:
        await message.answer(f"Ошибка генерации: {e}")

async def main():
    logging.info("Starting bot...")
    # Wait for DB to be ready (simplistic approach, usually handled by checking loop or depends_on condition)
    await asyncio.sleep(5) 
    try:
        await init_db()
        logging.info("Database initialized.")
    except Exception as e:
        logging.error(f"Failed to init DB: {e}")

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
