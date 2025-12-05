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
        reply_markup=get_main_menu(user.access_level),
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

def get_user_limits(level: str):
    """
    Returns (max_refs, can_use_high_res)
    """
    if level == 'admin' or level == 'full':
        return 5, True
    if level == 'basic':
        return 3, False
    # Demo
    return 0, False

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
    dialogue = State()

# --- Keyboards ---

def get_main_menu(level: str = "demo"):
    url = f"https://DNStrokin.github.io/nano_banana_bot/?level={level}"
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="🍌 Открыть приложение", web_app=WebAppInfo(url=url))],
            [types.KeyboardButton(text="⚡ Flash"), types.KeyboardButton(text="🍌 Pro")],
            [types.KeyboardButton(text="📸 Imagen"), types.KeyboardButton(text="❓ Помощь")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите режим или откройте приложение"
    )

def get_cancel_menu():
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="❌ Отмена")]
        ],
        resize_keyboard=True
    )

def get_dialogue_menu():
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="✅ Завершить диалог")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Напишите правки для картинки..."
    )

# --- Command Handlers ---

@dp.message(Command("cancel"))
@dp.message(F.text.lower() == "отмена")
@dp.message(F.text.lower() == "cancel")
@dp.message(F.text == "✅ Завершить диалог")
async def cmd_cancel(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    level = user.access_level if user else 'demo'

    # Cleanup session
    if message.chat.id in chat_sessions:
        del chat_sessions[message.chat.id]

    current_state = await state.get_state()
    if current_state is None:
        await message.answer("А нечего отменять. Мы на старте.", reply_markup=get_main_menu(level))
        return

    await state.clear()
    await message.answer("🚫 Операция отменена. Возвращаемся в главное меню.", reply_markup=get_main_menu(level))

@dp.message(F.web_app_data)
async def handle_web_app_data(message: types.Message, state: FSMContext):
    try:
        data = json.loads(message.web_app_data.data)
    except:
        return

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

    if data.get('action') == 'generate':
        # Validate Resolution for Basic/Demo
        user = await get_user(message.chat.id)
        level = user.access_level if user else 'demo'
        _, can_high_res = get_user_limits(level)
        
        target_res = data.get('resolution', '1024x1024')
        if not can_high_res and target_res != '1024x1024':
             target_res = '1024x1024' # Force standard

        # Save params to FSM
        await state.update_data(
            prompt=data['prompt'],
            aspect_ratio=data.get('aspect_ratio', '1:1'),
            resolution=target_res,
            model=data.get('model', 'nano_banana')
        )
        
        use_ref = data.get('use_reference', False)
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
    # Setup Cleanup
    if message.chat.id in chat_sessions:
        del chat_sessions[message.chat.id]

    # Access Check
    if not await check_access(message.chat.id, model):
        user = await get_user(message.chat.id)
        level = user.access_level if user else 'demo'
        await message.answer(
            f"⛔ Псс, парень! Модель `{model}` тебе недоступна.\n"
            "Постучись админу (или /start для запроса).", 
            reply_markup=get_main_menu(level),
            parse_mode="Markdown"
        )
        return

    await state.set_state(GenStates.waiting_for_prompt)
    await state.update_data(model=model, ref_images=[], prompt="")
    
    model_messages = {
        "imagen": (
            "📸 **Режим: IMAGEN 4 FAST**\n\n"
            "Фотореалистичная генерация нового поколения. 🚀\n"
            "Опишите кадр, который хотите получить.\n\n"
            "📐 **AR:** Поддерживается (например, `--ar 16:9`).\n"
            "🚫 **Референсы:** Не поддерживаются в этом режиме.\n\n"
            "👇 Жду ваше описание..."
        ),
        "nano_banana": (
            "🍌 **Режим: NANO BANANA**\n\n"
            "Быстрая генерация на базе Gemini 2.5 Flash. ⚡\n"
            "Отлично понимает сложные промпты!\n\n"
            "📐 **AR:** `--ar 16:9`, `4:3` и др.\n"
            "📸 **Референсы:** Можно прикрепить до 3 фото.\n\n"
            "👇 Что рисуем?"
        ),
        "nano_banana_pro": (
            "🍌 **Режим: NANO BANANA PRO**\n\n"
            "Мощная модель Gemini 3 Pro с поддержкой диалога! 💬\n"
            "Максимальное качество и понимание контекста.\n\n"
            "📐 **AR:** `--ar 16:9`, `4:3` и др.\n"
            "🖥 **Разрешение:** `--2k`, `--4k` (для Full).\n"
            "📸 **Референсы:** До 5 штук (для Full).\n"
            "🗣 **Диалог:** После генерации можно просить правки.\n\n"
            "👇 Опишите вашу идею..."
        )
    }

    msg = model_messages.get(model, (
        f"🍌 **Режим: {model.upper()}**\n\n"
        "Опишите, что будем творить. 🎨\n"
        "В конце можно добавить `--ar 16:9`.\n\n"
        "👇 Жду ваших мыслей..."
    ))
    await message.answer(msg, reply_markup=get_cancel_menu(), parse_mode="Markdown")



@dp.message(Command("help"))
@dp.message(F.text == "❓ Помощь")
async def cmd_help(message: types.Message):
    user = await get_user(message.chat.id)
    level = user.access_level if user else 'demo'
    
    help_text = (
        "📚 **Справка**\n\n"
        "⚡ **Flash**: Экономный и быстрый. Хорош для артов.\n"
        "🍌 **Pro**: Умный. Понимает нюансы и ведет диалог.\n"
        "📸 **Imagen**: Только для реалистичных фото.\n\n"
        "🎨 **WebApp**: Нажмите 'Открыть приложение', чтобы настроить всё визуально!"
    )
    await message.answer(help_text, parse_mode="Markdown", reply_markup=get_main_menu(level))

@dp.message(Command("pro"))
@dp.message(F.text == "🍌 Pro")
async def cmd_pro(message: types.Message, state: FSMContext):
    await start_generation_flow(message, state, "nano_banana_pro")

@dp.message(Command("flash"))
@dp.message(F.text == "⚡ Flash")
async def cmd_flash(message: types.Message, state: FSMContext):
    await start_generation_flow(message, state, "nano_banana")

@dp.message(Command("imagen"))
@dp.message(F.text == "📸 Imagen")
async def cmd_imagen(message: types.Message, state: FSMContext):
    await start_generation_flow(message, state, "imagen")



async def trigger_generation(message: types.Message, state: FSMContext):
    # 0. Context & Access
    user = await get_user(message.chat.id)
    level = user.access_level if user else 'demo'
    max_refs, can_high_res = get_user_limits(level)

    data = await state.get_data()
    prompt = data.get('prompt', '').strip()
    model = data.get('model')
    refs = data.get('ref_images', []) # List of file_ids
    
    # 1. Validation
    if not prompt: 
        await message.answer("⚠️ Эмм... А рисовать-то что? Напишите хоть пару слов.", reply_markup=get_cancel_menu())
        return # Keep state

    # 2. Ref limits
    if len(refs) > max_refs:
        refs = refs[:max_refs]
        await message.answer(f"✂️ Лимит фото для {level}: {max_refs}. Лишние убрал.")

    # 3. Parse AR (Robust)
    import re
    ar = data.get('aspect_ratio', '1:1')
    target_res = data.get('resolution', '1K')
    
    # Regex for various dashes: -, --, —, –
    # Matches: (dash)ar (space) (value)
    match_ar = re.search(r'(?:--|—|–|-)ar\s+(\d+:\d+)', prompt)
    if match_ar:
        ar = match_ar.group(1)
        # Remove the flag from prompt
        prompt = re.sub(r'(?:--|—|–|-)ar\s+\d+:\d+', '', prompt).strip()

    # Regex for resolution: --1k, --2k, --4k
    match_res = re.search(r'(?:--|—|–|-)(1k|2k|4k)', prompt, re.IGNORECASE)
    if match_res:
        requested_res = match_res.group(1).upper()
        # Remove flag
        prompt = re.sub(r'(?:--|—|–|-)(1k|2k|4k)', '', prompt, flags=re.IGNORECASE).strip()
        
        # Check permission
        if requested_res in ['2K', '4K']:
            if can_high_res:
                target_res = requested_res
            else:
                await message.answer(f"⚠️ Разрешение {requested_res} доступно только Full/Admin. Использую 1K.")
                target_res = '1K'
        else:
             target_res = '1K'

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
        "nano_banana": "Nano Banana (Gemini 2.5 Flash)",
        "nano_banana_pro": "Nano Banana Pro (Gemini 3 Pro)",
        "imagen": "Imagen 4 Fast"
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
        # Retrieve existing chat session if in dialogue mode
        chat_session = None
        current_state = await state.get_state()
        if current_state == GenStates.dialogue:
             chat_session = chat_sessions.get(message.chat.id)

        image_bytes, token_count, new_chat_session = await nano_service.generate_image(
            prompt=prompt,
            aspect_ratio=ar,
            resolution=target_res,
            model_type=model,
            reference_images=image_bytes_list,
            chat_session=chat_session
        )
        
        # Mark Completed
        await update_generation_status(gen_id, 'completed', token_count)
        
        # Save session if exists
        if new_chat_session:
            chat_sessions[message.chat.id] = new_chat_session

        # Format Caption
        model_display = MODEL_NAMES.get(model, model)
        token_text = f"Использовано {token_count} {get_token_suffix(token_count)}"
        
        final_caption = f"✨ Готово! {model_display}\n{token_text}\n\n🍌 @dimastro_banana_bot"

        # Logic for Dialogue continuation
        user = await get_user(message.chat.id)
        level = user.access_level if user else 'demo'
        
        keyboard = get_main_menu(level)
        
        if (level == 'admin' or level == 'full') and model == 'nano_banana_pro':
             final_caption += "\n\n💬 **Редактирование:** Напишите, что изменить (или нажмите кнопку)."
             await state.set_state(GenStates.dialogue)
             keyboard = get_dialogue_menu()
             # We keep data (model, etc) in state
        else:
             await state.clear()
             # Clear session if not continuing
             if message.chat.id in chat_sessions:
                 del chat_sessions[message.chat.id]
        
        # Send Result
        photo = BufferedInputFile(image_bytes, filename=f"banana_{model}.png")
        await message.answer_photo(
            photo, 
            caption=final_caption,
            reply_markup=keyboard 
        )
        
        # Cleanup status
        try:
            await processing_msg.delete()
        except:
            pass

    except Exception as e:
        await update_generation_status(gen_id, 'failed')
        await message.answer(f"❌ Упс! Ошибка: {e}", reply_markup=get_main_menu(level))
        if message.chat.id in chat_sessions:
            del chat_sessions[message.chat.id]
    
# In-memory session storage (simple approach for single instance bot)
chat_sessions = {}
processing_tasks = {}

@dp.message(GenStates.dialogue)
async def process_dialogue_step(message: types.Message, state: FSMContext):
    # All commands/cancels are handled by upstream handlers.
    # If we are here, it's a refinement prompt text.
    
    # Treat as refinement prompt
    await state.update_data(prompt=message.text) 
    await state.update_data(ref_images=[]) # Clear refs for text-only edit
    
    await trigger_generation(message, state)

@dp.message(GenStates.waiting_for_prompt)
async def process_prompt_input(message: types.Message, state: FSMContext):
    # This handler catches EVERYTHING: text, photos
    
    data = await state.get_data()
    
    # 1. Capture Text/Caption
    text = message.text or message.caption
    
    # Check for Cancel explicitly
    if text and text.lower() in ["отмена", "cancel", "❌ отмена"]:
         await cmd_cancel(message, state)
         return

    if text and not text.startswith("/"): # Ignore commands just in case
        await state.update_data(prompt=text) # Overwrite prompt with latest text
    
    # 2. Capture Photos
    if message.photo:
        user_level = (await get_user(message.from_user.id)).access_level
        max_refs, _ = get_user_limits(user_level)
        
        if max_refs == 0:
             await message.answer("⚠️ Ваш уровень доступа (Demo) работает только с текстом. Фото не принимаются.")
             return

        refs = list(data.get('ref_images', []))
        current_refs_count = len(refs)
        if current_refs_count >= max_refs:
            await message.answer(f"⚠️ Лимит фото для вашего уровня: {max_refs}. Это фото не добавлено.")
            # Don't add, but continue debounce so generation starts with existing refs
        else:
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

@dp.message(F.text)
async def handle_unknown_text(message: types.Message, state: FSMContext):
    # This triggers if no other handler caught it (e.g. not a command, not in FSM state)
    user = await get_user(message.chat.id)
    level = user.access_level if user else 'demo'

    msg = (
        "🤖 **Я вас не понял.**\n"
        "Сейчас мы не в режиме генерации или диалога.\n\n"
        "🔹 **Хотите рисовать?** Выберите режим в меню (Flash/Pro/Imagen).\n"
        "🔹 **Хотите поговорить?** Диалог поддерживается **только** в режиме `/pro` (для Full/Admin). В режимах Flash/Imagen диалог после генерации не работает.\n\n"
        "Для новой генерации нажмите одну из кнопок ниже 👇"
    )
    await message.answer(msg, reply_markup=get_main_menu(level), parse_mode="Markdown")

async def main():
    logging.info("Starting bot...")
    
    # Set bot commands menu
    commands = [
        types.BotCommand(command="start", description="Запустить бота"),
        types.BotCommand(command="help", description="Справка и список команд"),
        types.BotCommand(command="pro", description="Nano Banana PRO (Gemini 3 Pro)"),
        types.BotCommand(command="flash", description="Nano Banana (Gemini 2.5 Flash)"),
        types.BotCommand(command="imagen", description="Imagen 4 (Только фото)"),
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
