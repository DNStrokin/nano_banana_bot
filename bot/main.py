import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.types import WebAppInfo, BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram import F
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
import json
from config import config
from database import init_db, add_or_update_user, get_user, update_user_access, log_generation, get_stats, get_all_users_stats, update_generation_status
from nano_service import nano_service

# Configure logging
logging.basicConfig(level=logging.INFO)

# Initialize Bot and Dispatcher
bot = Bot(token=config.BOT_TOKEN.get_secret_value())
dp = Dispatcher()

# --- Auth Logic ---

ADMIN_IDS = [int(id.strip()) for id in config.ADMIN_IDS.split(",")]

async def check_access(user_id: int, model: str) -> bool:
    user = await get_user(user_id)
    if not user:
        return False
    
    level = user.access_level
    if level == 'admin' or user_id in ADMIN_IDS:
        return True
    if level == 'banned' or level == 'pending':
        return False
        
    # Full access
    if level == 'full':
        return True
        
    # Basic: Flash + Imagen
    if level == 'basic' and model in ['nano_banana', 'imagen']:
        return True
        
    # Demo: Imagen only
    if level == 'demo' and model == 'imagen':
        return True
        
    return False

async def notify_admins_request(user: types.User):
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Full Access", callback_data=f"access:full:{user.id}")],
        [InlineKeyboardButton(text="Basic (Flash+Img)", callback_data=f"access:basic:{user.id}")],
        [InlineKeyboardButton(text="Demo (Img Only)", callback_data=f"access:demo:{user.id}")],
        [InlineKeyboardButton(text="🚫 Отклонить", callback_data=f"access:banned:{user.id}")]
    ])
    
    text = (
        f"👤 **Новый пользователь запросил доступ!**\n"
        f"Name: {user.full_name}\n"
        f"Username: @{user.username}\n"
        f"ID: `{user.id}`"
    )
    
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, reply_markup=markup, parse_mode="Markdown")
        except:
            pass # Admin might have blocked bot

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user, created = await add_or_update_user(
        message.from_user.id, 
        message.from_user.username, 
        message.from_user.full_name
    )
    
    # If admin
    if message.from_user.id in ADMIN_IDS:
        await update_user_access(message.from_user.id, "admin")
        user.access_level = "admin" # Update local object so next messages are correct
        await message.answer("👑 Привет, Создатель! Вы авторизованы как Админ.")
        # Show standard menu too
    
    elif user.access_level == 'pending':
        await message.answer(
            f"Привет, {message.from_user.full_name}! 👋\n\n"
            "Bot находится в закрытом режиме. Я отправил запрос администратору.\n"
            "Как только доступ подтвердят, я пришлю уведомление!"
        )
        if created or user.access_level == 'pending': 
            if created:
                await notify_admins_request(message.from_user)
        return

    elif user.access_level == 'banned':
        return # Ignore banned
        
    # If access granted, show menu
    await message.answer(
        f"С возвращением, {message.from_user.full_name}! 🍌\n"
        f"Ваш уровень доступа: **{user.access_level.upper()}**.\n"
        f"Нажми кнопку ниже, чтобы открыть генератор.",
        reply_markup=get_main_menu(),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data.startswith("access:"))
async def process_access_callback(callback: CallbackQuery):
    # Data format: access:level:user_id
    parts = callback.data.split(":")
    level = parts[1]
    user_id = int(parts[2])
    
    # 1. Update DB
    await update_user_access(user_id, level)
    
    # 2. Update Admin Message
    admin_name = callback.from_user.first_name
    await callback.message.edit_text(
        f"{callback.message.text}\n\n✅ **Обработано {admin_name}:** Присвоен статус `{level}`",
        parse_mode="Markdown",
        reply_markup=None
    )
    
    # 3. Notify User
    try:
        if level == 'banned':
            await bot.send_message(user_id, "⛔ Ваш запрос на доступ был отклонен.")
        else:
            await bot.send_message(
                user_id, 
                f"🎉 **Доступ разрешен!**\nВаш уровень: `{level}`\n\nНажмите /start чтобы начать.",
                parse_mode="Markdown"
            )
    except:
        pass # User blocked bot
    
    await callback.answer()

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
        
    users_count, gens_count, recent_gens = await get_stats()
    
    stats_text = (
        f"📊 **Статистика**\n"
        f"👥 Пользователей: `{users_count}`\n"
        f"🖼️ Генераций: `{gens_count}`\n\n"
        f"⏳ **Последние 5:**\n"
    )
    
    for gen in recent_gens:
        stats_text += f"- `{gen.id}`: `{gen.model}` ({gen.status})\n"
        
    await message.answer(stats_text, parse_mode="Markdown")

    help_text = (
        "🛠 **Admin Commands**\n\n"
        "👥 `/users` - Список пользователей и статистика\n\n"
        "🔐 **Управление доступом:**\n"
        "`/set_access [ID] [level]`\n"
        "Levels: `full`, `basic`, `demo`, `banned`"
    )
    await message.answer(help_text, parse_mode="Markdown")

@dp.message(Command("users"))
async def cmd_users(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    stats_list = await get_all_users_stats()
    
    # Format message
    lines = ["👥 **Users List**"]
    lines.append(f"{'ID':<10} | {'Name':<15} | {'Lvl':<7} | {'Gen':<3} | {'Tok'}")
    lines.append("-" * 50)
    
    for user_stats in stats_list:
        uid = str(user_stats.id)
        name = str(user_stats.full_name)[:15] # Cast to str just in case
        lvl = str(user_stats.access_level)[:7]
        cnt = str(user_stats.gens_count)
        # Handle None token count safely
        t_val = user_stats.total_tokens
        if t_val is None:
            t_val = 0
        tok = f"{t_val / 1000:.1f}k"
        
        lines.append(f"`{uid:<10}` | {name:<15} | {lvl:<7} | {cnt:<3} | {tok}")
        
    text = "\n".join(lines)
    # Truncate if too long
    if len(text) > 4000:
        text = text[:4000] + "\n... (truncated)"
        
    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("set_access"))
async def cmd_set_access(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
        
    args = message.text.split()
    if len(args) != 3:
        await message.answer("Usage: `/set_access 12345 full`", parse_mode="Markdown")
        return
        
    try:
        user_id = int(args[1])
        level = args[2]
        if level not in ['full', 'basic', 'demo', 'banned', 'pending']:
            await message.answer("Invalid level.")
            return
            
        await update_user_access(user_id, level)
        await message.answer(f"✅ User {user_id} set to {level}.")
        
        # Try notify
        try:
            await bot.send_message(user_id, f"🔄 Ваш уровень доступа изменен на: `{level}`", parse_mode="Markdown")
        except:
            pass
            
    except Exception as e:
         await message.answer(f"Error: {e}")

# FSM States
class GenStates(StatesGroup):
    waiting_for_prompt = State()
    waiting_for_reference = State() # Keep for Web App compatibility if needed

# --- Keyboards ---

def get_main_menu():
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="🍌 Открыть приложение", web_app=WebAppInfo(url="https://DNStrokin.github.io/nano_banana_bot/"))]
        ],
        resize_keyboard=True
    )

def get_cancel_menu():
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="❌ Отмена")]
        ],
        resize_keyboard=True
    )

# --- Command Handlers ---

@dp.message(Command("cancel"))
@dp.message(F.text.lower() == "отмена")
@dp.message(F.text.lower() == "cancel")
async def cmd_cancel(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("А нечего отменять. Мы на старте.", reply_markup=get_main_menu())
        return

    await state.clear()
    await message.answer("🚫 Операция отменена. Возвращаемся в главное меню.", reply_markup=get_main_menu())

@dp.message(F.web_app_data)
async def handle_web_app_data(message: types.Message, state: FSMContext):
    try:
        data = json.loads(message.web_app_data.data)
    except:
        return

    if data.get('action') == 'generate':
        use_ref = data.get('use_reference', False)
        
        # Save params to FSM
        await state.update_data(
            prompt=data['prompt'],
            aspect_ratio=data.get('aspect_ratio', '1:1'),
            resolution=data.get('resolution', '1024x1024'),
            model=data.get('model', 'nano_banana')
        )

        if use_ref:
            # Reusing the unified input handler state!
            await state.set_state(GenStates.waiting_for_prompt)
            await message.answer(
                "🍌 **Принято!** Теперь отправьте 1-3 фото-референса.\n",
                parse_mode="Markdown",
                reply_markup=get_cancel_menu()
            )
        else:
            # Immediate generation
            await trigger_generation(message, state)

async def start_generation_flow(message: types.Message, state: FSMContext, model: str):
    # Access Check
    if not await check_access(message.chat.id, model):
        await message.answer(
            f"⛔ Псс, парень! Модель `{model}` тебе недоступна.\n"
            "Постучись админу (или /start для запроса).", 
            reply_markup=get_main_menu(),
            parse_mode="Markdown"
        )
        return

    await state.set_state(GenStates.waiting_for_prompt)
    await state.update_data(model=model, ref_images=[], prompt="")
    
    msg = (
        f"🍌 **Режим: {model.upper()}**\n\n"
        "Опишите, что будем творить. 🎨\n"
        "В конце можно добавить `--ar 16:9` (или `4:3`, `3:4`...).\n\n"
        "📸 **Референсы:** Можно прикрепить до 3 штук (скрепкой).\n\n"
        "👇 Жду ваших мыслей..."
    )
    await message.answer(msg, reply_markup=get_cancel_menu(), parse_mode="Markdown")

@dp.message(Command("pro"))
async def cmd_pro(message: types.Message, state: FSMContext):
    await start_generation_flow(message, state, "nano_banana_pro")

@dp.message(Command("flash"))
async def cmd_flash(message: types.Message, state: FSMContext):
    await start_generation_flow(message, state, "nano_banana")

@dp.message(Command("imagen"))
async def cmd_imagen(message: types.Message, state: FSMContext):
    await start_generation_flow(message, state, "imagen")

@dp.message(F.web_app_data)
async def handle_web_app_data(message: types.Message, state: FSMContext):
    data = json.loads(message.web_app_data.data)
    
    if data.get('action') == 'generate':
        use_ref = data.get('use_reference', False)
        
        # Save params to FSM
        await state.update_data(
            prompt=data['prompt'],
            aspect_ratio=data.get('aspect_ratio', '1:1'),
            resolution=data.get('resolution', '1024x1024'),
            model=data.get('model', 'nano_banana')
        )

        if use_ref:
            # Reusing the unified input handler state!
            await state.set_state(GenStates.waiting_for_prompt)
            await message.answer(
                "🍌 **Принято!** Теперь отправьте 1-3 фото-референса.\n",
                parse_mode="Markdown",
                reply_markup=get_cancel_menu()
            )
        else:
            # Immediate generation
            await trigger_generation(message, state)

async def trigger_generation(message: types.Message, state: FSMContext):
    data = await state.get_data()
    prompt = data.get('prompt', '').strip()
    model = data.get('model')
    refs = data.get('ref_images', []) # List of file_ids
    
    # 1. Validation
    if not prompt: 
        await message.answer("⚠️ Эмм... А рисовать-то что? Напишите хоть пару слов.", reply_markup=get_cancel_menu())
        return # Keep state

    # 2. Ref limits
    if len(refs) > 3:
        await message.answer(f"⚠️ Ого, {len(refs)} фото! Беру только первые 3, остальные — в архив.", reply_markup=get_cancel_menu())
        refs = refs[:3] # Slice
    
    # 3. Parse AR
    ar = "1:1"
    if "--ar" in prompt:
        parts = prompt.split("--ar")
        prompt = parts[0].strip()
        if len(parts) > 1:
            ar_candidates = parts[1].strip().split()
            if ar_candidates:
                ar = ar_candidates[0]

    # 4. Status Message
    from aiogram.utils.markdown import hide_link
    ref_info = f"\n📎 Refs: {len(refs)}" if refs else ""
    status_text = (
        f"🍌 **Генерирую...** (`{model}`)\n"
        f"📝 `{prompt[:50] + '...' if len(prompt)>50 else prompt}`\n"
        f"📐 AR: `{ar}`"
        f"{ref_info}"
    )
    
    processing_msg = await message.answer(status_text, parse_mode="Markdown")
    
    # Log
    gen_id = await log_generation(message.chat.id, model, prompt, ar, None, 'pending')

    # Helpers for caption
    def get_token_suffix(count: int) -> str:
        if count % 10 == 1 and count % 100 != 11:
            return "токен"
        elif 2 <= count % 10 <= 4 and (count % 100 < 10 or count % 100 >= 20):
            return "токена"
        else:
            return "токенов"

    MODEL_NAMES = {
        "nano_banana": "Nano Banana (Flash)",
        "nano_banana_pro": "Nano Banana (Pro)",
        "imagen": "Imagen 3 (Fast)"
    }

    try:
        # Download refs
        image_bytes_list = []
        if refs:
            bot_instance = message.bot
            for file_id in refs:
                file = await bot_instance.get_file(file_id)
                io_bytes = await bot_instance.download_file(file.file_path)
                image_bytes_list.append(io_bytes.read())

        # Call API
        image_bytes, token_count = await nano_service.generate_image(
            prompt=prompt,
            aspect_ratio=ar,
            resolution="1024x1024", 
            model_type=model,
            reference_images=image_bytes_list
        )
        
        # Mark Completed
        await update_generation_status(gen_id, 'completed', token_count)
        
        # Format Caption
        model_display = MODEL_NAMES.get(model, model)
        token_text = f"Использовано {token_count} {get_token_suffix(token_count)}"
        
        # Send Result
        photo = BufferedInputFile(image_bytes, filename=f"banana_{model}.png")
        await message.answer_photo(
            photo, 
            caption=f"✨ Готово! {model_display}\n{token_text}\n\n🍌 @dimastro_banana_bot",
            reply_markup=get_main_menu() 
        )
        
        # Cleanup status
        try:
            await processing_msg.delete()
        except:
            pass

    except Exception as e:
        await update_generation_status(gen_id, 'failed')
        await message.answer(f"❌ Упс! Ошибка: {e}", reply_markup=get_main_menu())
    finally:
        await state.clear()

# Task storage for debounce
processing_tasks = {}

@dp.message(GenStates.waiting_for_prompt)
async def process_prompt_input(message: types.Message, state: FSMContext):
    # This handler catches EVERYTHING: text, photos
    
    data = await state.get_data()
    
    # 1. Capture Text/Caption
    text = message.text or message.caption
    if text and not text.startswith("/"): # Ignore commands just in case
        await state.update_data(prompt=text) # Overwrite prompt with latest text
    
    # 2. Capture Photos
    if message.photo:
        refs = data.get('ref_images', [])
        photo = message.photo[-1] # Best quality
        refs.append(photo.file_id)
        await state.update_data(ref_images=refs)

    # 3. Debounce (Smart Delay)
    key = (message.chat.id, message.from_user.id)
    if key in processing_tasks:
        processing_tasks[key].cancel()
    
    async def delayed_generation():
        await asyncio.sleep(2.0)
        del processing_tasks[key]
        await trigger_generation(message, state)

    processing_tasks[key] = asyncio.create_task(delayed_generation())

async def main():
    logging.info("Starting bot...")
    
    # Set bot commands menu
    commands = [
        types.BotCommand(command="start", description="Запустить бота"),
        types.BotCommand(command="help", description="Справка и список команд"),
        types.BotCommand(command="pro", description="Генерация Pro (Gemini 3)"),
        types.BotCommand(command="flash", description="Генерация Flash (Быстро)"),
        types.BotCommand(command="imagen", description="Генерация Imagen (Фото)"),
    ]
    await bot.set_my_commands(commands)
    
    # Wait for DB to be ready
    await asyncio.sleep(5) 
    try:
        await init_db()
        logging.info("Database initialized.")
    except Exception as e:
        logging.error(f"Failed to init DB: {e}")

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
