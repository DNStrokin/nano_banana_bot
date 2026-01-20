import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.types import WebAppInfo, BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram import F
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
import json
from datetime import datetime
from config import config
from database import init_db, add_or_update_user, get_user, update_user_access, log_generation, get_stats, get_all_users_stats, update_generation_status, get_user_balance, update_balance, set_user_tariff, User, Generation, async_session
from sqlalchemy import select, func
from nano_service import nano_service
from pricing import calculate_cost, validate_request, TARIFFS, PACKAGES, MODEL_PRICES, RUB_TO_NC, MODEL_DISPLAY, ASPECT_RATIOS, RESOLUTION_SURCHARGES


# Configure logging
logging.basicConfig(level=logging.INFO)

# Initialize Bot and Dispatcher
bot = Bot(token=config.BOT_TOKEN.get_secret_value())
dp = Dispatcher()

# --- Auth Logic ---

ADMIN_IDS = [int(id.strip()) for id in config.ADMIN_IDS.split(",")]

async def enforce_tariff_expiry(user: User | None, message: types.Message) -> User | None:
    """
    Если срок тарифа истёк и это не demo/admin — даунгрейдим до DEMO и уведомляем.
    """
    if not user:
        return user
    if user.tariff_expires_at and user.tariff not in ["demo", "admin"]:
        if datetime.now() >= user.tariff_expires_at:
            await set_user_tariff(user.id, "demo", days=None)
            await update_user_access(user.id, "demo")
            user.tariff = "demo"
            user.tariff_expires_at = None
            await message.answer("⏳ Срок вашей подписки истёк. Тариф переключен на DEMO.")
    return user

async def check_access(user_id: int, model: str) -> bool:
    user = await get_user(user_id)
    if not user:
        return False
    
    if user.access_level == 'banned':
        return False
    if user.access_level == 'admin' or user_id in ADMIN_IDS:
        return True

    # Use Tariff Logic
    # We pass placeholders for res/refs/ar because this is just a preliminary "Can I open this menu?" check
    # usage checks happen in trigger_generation
    valid, reason = validate_request(user.tariff, model, None, 0, "1:1")
    return valid

async def notify_admins_request(user: User):
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Закрыть", callback_data="cancel_action")]
    ])
    
    text = (
        f"👤 **Новый пользователь зарегистрирован!**\n"
        f"Name: {user.full_name}\n"
        f"Username: @{user.username}\n"
        f"ID: `{user.id}`\n"
        f"Тариф: `{user.tariff}`\n"
        f"Баланс: `{user.balance} NC`"
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

    # Проверка истечения тарифа с авто-даунгрейдом и уведомлением
    user = await enforce_tariff_expiry(user, message)
    
    # If admin
    if message.from_user.id in ADMIN_IDS:
        await update_user_access(message.from_user.id, "admin")
        user.tariff = "admin"
        await message.answer("👑 Привет, Создатель! Вы авторизованы как Админ.\nТариф установлен на: **ADMIN**")
        # Show standard menu too
    
    # Open Registration Logic
    # Update local object access level if it was pending, because now we trust tariff
    if user.access_level == 'pending':
        await update_user_access(message.from_user.id, "demo") # Auto-approve as Demo
        user.access_level = "demo"
    
    if user.access_level == 'banned' or user.tariff == 'banned':
        return # Ignore banned

    # Welcome Message
    # If newly created
    if created:
        await message.answer(
            f"🍌 **Добро пожаловать в Nano Banana!**\n\n"
            f"🎁 Вам начислен приветственный бонус: **500 NC**!\n"
            f"Ваш тариф: **ДЕМО**.\n\n"
            f"Используйте /profile чтобы проверить баланс.\n"
            f"Нажмите кнопку ниже, чтобы начать рисовать!",
            reply_markup=get_main_menu(user.tariff, user.balance),
            parse_mode="Markdown"
        )
        await notify_admins_request(user)
    else:
        await message.answer(
            f"С возвращением, {message.from_user.full_name}! 🍌\n"
            f"Ваш тариф: **{user.tariff.upper()}**.\n"
            f"Нажми кнопку ниже, чтобы открыть генератор.",
            reply_markup=get_main_menu(user.tariff, user.balance),
            parse_mode="Markdown"
        )



def get_user_limits(level: str):
    """
    Returns (max_refs, can_use_high_res)
    """
    level = level.lower()
    t = TARIFFS.get(level)
    if t:
        return t.get('max_refs', 0), t.get('can_use_2k_4k', False)
        
    # Validation for banned/pending
    return 0, False

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
        
    users_count, gens_count, recent_gens = await get_stats()
    
    text = (
        f"👑 **Админ Панель**\n\n"
        f"📊 **Статистика:**\n"
        f"👥 Пользователи: `{users_count}`\n"
        f"🖼️ Генерации: `{gens_count}`"
    )
    
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Список пользователей", callback_data="admin:users")],
        [InlineKeyboardButton(text="❓ Помощь по командам", callback_data="admin:help")],
        [InlineKeyboardButton(text="🔁 Обновить статистику", callback_data="admin:refresh")],
        [InlineKeyboardButton(text="❌ Закрыть", callback_data="cancel_action")]
    ])
    
    await message.answer(text, parse_mode="Markdown", reply_markup=markup)

class AdminStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_balance = State()
    waiting_for_tariff_duration = State() # Optional, if we want custom

@dp.callback_query(F.data.in_({"admin:users", "admin:help", "admin:refresh", "admin:user_info", "admin:back_main"}))
async def process_admin_callback(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return
        
    action = callback.data.split(":")[1]
    
    if action == "users":
        await send_users_list(callback.message)
        await callback.answer()
        
    elif action == "user_info":
        await callback.message.edit_text(
            "🔎 **Поиск пользователя**\n\nВведите ID пользователя или Username (без @):",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:refresh")]
            ])
        )
        await state.set_state(AdminStates.waiting_for_user_id)
        await callback.answer()

    elif action == "help":
        help_text = (
            "🛠 **Admin Commands**\n\n"
            "👥 `/users` - Список пользователей и статистика\n\n"
            "🔐 **Управление доступом:**\n"
            "`/set_access [ID] [level]`\n"
            "Levels: `full`, `basic`, `demo`, `banned`\n\n"
            "💰 **Финансы:**\n"
            "`/add_nc [ID] [amount]` - Выдать валюту"
        )
        await callback.message.answer(help_text, parse_mode="Markdown")
        await callback.answer()
        
    elif action == "refresh" or action == "back_main":
        await state.clear()
        # Refresh the stats message
        users_count, gens_count, recent_gens = await get_stats()
        text = (
            f"👑 **Админ Панель**\n\n"
            f"📊 **Статистика:**\n"
            f"👥 Пользователи: `{users_count}`\n"
            f"🖼️ Генерации: `{gens_count}`"
        )
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👥 Список пользователей", callback_data="admin:users")],
            [InlineKeyboardButton(text="👤 Инфо о пользователе", callback_data="admin:user_info")],
            [InlineKeyboardButton(text="❓ Помощь по командам", callback_data="admin:help")],
            [InlineKeyboardButton(text="🔁 Обновить статистику", callback_data="admin:refresh")],
            [InlineKeyboardButton(text="❌ Закрыть", callback_data="cancel_action")]
        ])
        
        # If it was a 'back' action, we might need to send a new message if the previous one was deleted or is too far up
        # But 'edit_text' usually works if we are within the same message flow
        try:
            await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=markup)
        except:
             # Fallback if we can't edit (e.g. different message type), send new
            await callback.message.answer(text, parse_mode="Markdown", reply_markup=markup)
            
        await callback.answer("Статистика обновлена")

# Handler for User Search Input
@dp.message(AdminStates.waiting_for_user_id)
async def process_admin_user_search(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
        
    query = message.text.strip()
    
    # Try to find user
    user = None
    if query.isdigit():
        user = await get_user(int(query))
    else:
        # Search by username logic would go here if implemented in DB
        # For now, simplistic ID search
        await message.answer("❌ Пока поддерживается только поиск по ID.")
        return

    if not user:
        await message.answer(
            "❌ Пользователь не найден.\nПопробуйте снова или нажмите 'Отмена'",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="admin:back_main")]
            ])
        )
        return
        
    # User found, show Manage Menu
    await state.clear() # Clear state as we are now in "menu mode" (stateless or callback-driven)
    await show_user_manage_menu(message, user)


async def get_user_manage_content(user: User):
    # Fetch additional stats
    stmt = select(func.count(Generation.id)).where(Generation.user_id == user.id)
    async with async_session() as session:
        gens_count = (await session.execute(stmt)).scalar() or 0
        
        stmt_tokens = select(func.sum(Generation.tokens_used)).where(Generation.user_id == user.id)
        total_tokens = (await session.execute(stmt_tokens)).scalar() or 0

    tariff_upper = user.tariff.upper()
    
    expires_info = "♾️ Бессрочно"
    if user.tariff_expires_at:
        expires_info = user.tariff_expires_at.strftime('%Y-%m-%d')
        
    text = (
        f"👤 **Управление пользователем**\n\n"
        f"🆔 ID: `{user.id}`\n"
        f"📛 Имя: {user.full_name}\n"
        f"💳 Тариф: **{tariff_upper}**\n"
        f"📅 Истекает: `{expires_info}`\n"
        f"💰 Баланс: `{user.balance} NC`\n"
        f"📊 Генераций: `{gens_count}`\n"
        f"🔢 Токены: `{total_tokens}`"
    )
    
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏷 Сменить тариф", callback_data=f"admin:manage:tariff:{user.id}")],
        [InlineKeyboardButton(text="💰 Изменить баланс", callback_data=f"admin:manage:balance:{user.id}")],
        [InlineKeyboardButton(text="⏱ Срок действия", callback_data=f"admin:manage:duration:{user.id}")],
        [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="admin:back_main")]
    ])
    return text, markup

async def show_user_manage_menu(message: types.Message, user: User):
    text, markup = await get_user_manage_content(user)
    await message.answer(text, parse_mode="Markdown", reply_markup=markup)

@dp.callback_query(F.data.startswith("admin:manage:"))
async def process_admin_manage_callback(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return
        
    parts = callback.data.split(":")
    action = parts[2]
    target_user_id = int(parts[3])
    
    if action == "tariff":
        # Show tariff list
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚡ Basic", callback_data=f"admin:set_tariff:{target_user_id}:basic")],
            [InlineKeyboardButton(text="🔥 Full", callback_data=f"admin:set_tariff:{target_user_id}:full")],
            [InlineKeyboardButton(text="🍌 Demo", callback_data=f"admin:set_tariff:{target_user_id}:demo")],
            [InlineKeyboardButton(text="👑 Admin", callback_data=f"admin:set_tariff:{target_user_id}:admin")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"admin:manage:back:{target_user_id}")]
        ])
        await callback.message.edit_text(f"👇 Выберите новый тариф для пользователя `{target_user_id}`:", reply_markup=markup, parse_mode="Markdown")
        await callback.answer()

    elif action == "duration":
        # Show duration list
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="1 Месяц", callback_data=f"admin:set_duration:{target_user_id}:1")],
            [InlineKeyboardButton(text="3 Месяца", callback_data=f"admin:set_duration:{target_user_id}:3")],
            [InlineKeyboardButton(text="6 Месяцев", callback_data=f"admin:set_duration:{target_user_id}:6")],
            [InlineKeyboardButton(text="12 Месяцев", callback_data=f"admin:set_duration:{target_user_id}:12")],
            [InlineKeyboardButton(text="♾️ Бессрочно", callback_data=f"admin:set_duration:{target_user_id}:unlimited")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"admin:manage:back:{target_user_id}")]
        ])
        await callback.message.edit_text(f"⏳ Выберите срок действия для пользователя `{target_user_id}`:", reply_markup=markup, parse_mode="Markdown")
        await callback.answer()

    elif action == "balance":
        # Ask for amount
        await callback.message.edit_text(
            f"💰 Введите новый баланс для пользователя `{target_user_id}` (целое число NC):", 
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data=f"admin:manage:back:{target_user_id}")]])
        )
        await state.set_state(AdminStates.waiting_for_balance)
        await state.update_data(target_user_id=target_user_id, prompt_message_id=callback.message.message_id)
        await callback.answer()
        
    elif action == "back":
        # Back to manage menu
        user = await get_user(target_user_id)
        if user:
            await callback.message.delete() # Clean up old menu
            await show_user_manage_menu(callback.message, user) # Send new one (message object hack)
        else:
            await callback.answer("User not found")

async def delete_message_delayed(message: types.Message, delay: int):
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except:
        pass

@dp.callback_query(F.data.startswith("admin:set_tariff:"))
async def process_admin_set_tariff(callback: CallbackQuery):
    parts = callback.data.split(":")
    user_id = int(parts[2])
    tariff = parts[3]
    
    await set_user_tariff(user_id, tariff)
    # await callback.answer(f"Тариф изменен на {tariff}") # Toast is easy to miss
    await callback.answer()
    
    # Send temp notification
    msg = await callback.message.answer(f"✅ Тариф пользователя {user_id} изменен на **{tariff.upper()}**", parse_mode="Markdown")
    asyncio.create_task(delete_message_delayed(msg, 3))
    
    # Return to menu
    user = await get_user(user_id)
    await callback.message.delete()
    await show_user_manage_menu(callback.message, user)

@dp.callback_query(F.data.startswith("admin:set_duration:"))
async def process_admin_set_duration(callback: CallbackQuery):
    parts = callback.data.split(":")
    user_id = int(parts[2])
    months_str = parts[3]
    
    days = None
    msg_text = "✅ Тариф установлен: **Бессрочно**"
    
    if months_str != "unlimited":
        months = int(months_str)
        days = months * 30
        msg_text = f"✅ Срок продлен на **{months} мес.**"

    user = await get_user(user_id)
    await set_user_tariff(user_id, user.tariff, days=days)
    
    await callback.answer()
    
    # Temp notification
    msg = await callback.message.answer(msg_text, parse_mode="Markdown")
    asyncio.create_task(delete_message_delayed(msg, 3))
    
    user = await get_user(user_id) # Refresh
    await callback.message.delete()
    await show_user_manage_menu(callback.message, user)

@dp.message(AdminStates.waiting_for_balance)
async def process_balance_input(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
        
    # Delete admin input immediately to keep chat clean
    try:
        await message.delete()
    except:
        pass

    data = await state.get_data()
    target_user_id = data.get("target_user_id")
    prompt_message_id = data.get("prompt_message_id")
    
    try:
        amount = int(message.text.strip())
        
        user = await get_user(target_user_id)
        delta = amount - user.balance
        await update_balance(target_user_id, delta)
        
        # Prepare Menu Content (Plain)
        user = await get_user(target_user_id) # Refresh
        menu_text, menu_markup = await get_user_manage_content(user)
        
        # Temp Success Msg
        msg = await message.answer(f"✅ Баланс пользователя {target_user_id} установлен на **{amount} NC**.", parse_mode="Markdown")
        asyncio.create_task(delete_message_delayed(msg, 3))
        
        # Try to edit the prompt message back to menu
        success = False
        if prompt_message_id:
            try:
                await bot.edit_message_text(
                    text=menu_text,
                    chat_id=message.chat.id,
                    message_id=prompt_message_id,
                    reply_markup=menu_markup,
                    parse_mode="Markdown"
                )
                success = True
            except Exception as e:
                pass 
        
        if not success:
            await message.answer(menu_text, parse_mode="Markdown", reply_markup=menu_markup)
        
        await state.clear()
        
    except ValueError:
        # Invalid input: Send temp error message
        msg = await message.answer("❌ Введите корректное число.")
        asyncio.create_task(delete_message_delayed(msg, 3))

async def send_users_list(message: types.Message):
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
        
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Инфо о пользователе", callback_data="admin:user_info")],
        [InlineKeyboardButton(text="❌ Закрыть", callback_data="cancel_action")]
    ])
        
    await message.answer(text, parse_mode="Markdown", reply_markup=markup)

@dp.message(Command("users"))
async def cmd_users(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await send_users_list(message)

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
        if level not in list(TARIFFS.keys()) + ['banned', 'pending']:
            await message.answer(f"Invalid level. Choose from: {', '.join(TARIFFS.keys())}, banned.")
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

@dp.message(Command("add_nc"))
async def cmd_add_nc(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
        
    args = message.text.split()
    if len(args) != 3:
        await message.answer("Usage: `/add_nc [user_id] [amount]`", parse_mode="Markdown")
        return
        
    try:
        user_id = int(args[1])
        amount = int(args[2])
        
        new_bal = await update_balance(user_id, amount)
        await message.answer(f"✅ Balance updated. User {user_id} now has {new_bal} NC.")
        try:
             await bot.send_message(user_id, f"💰 **Вам начислено {amount} NC!**\nТекущий баланс: {new_bal} NC", parse_mode="Markdown")
        except:
            pass
    except Exception as e:
        await message.answer(f"Error: {e}")

@dp.message(Command("profile"))
@dp.message(F.text.startswith("👤 Мой кабинет"))
async def cmd_profile(message: types.Message):
    user = await get_user(message.from_user.id)
    user = await enforce_tariff_expiry(user, message)
    if not user:
        return
        
    tariff_upper = user.tariff.upper()
    balance = user.balance
    
    expires_info = "\n♾️ Бессрочно"
    if user.tariff_expires_at:
        expires_info = f"\n📅 Истекает: `{user.tariff_expires_at.strftime('%Y-%m-%d')}`"
        
    msg = (
        f"👤 **Профиль Пилота**\n\n"
        f"📛 Имя: {user.full_name}\n"
        f"💳 Тариф: **{tariff_upper}**{expires_info}\n"
        f"💰 Баланс: **{balance} NC**"
    )
    
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="nav:buy")],
        [InlineKeyboardButton(text="⬆️ Сменить тариф", callback_data="nav:upgrade")]
    ])
    
    await message.answer(msg, parse_mode="Markdown", reply_markup=markup)

@dp.callback_query(F.data.startswith("nav:"))
async def process_nav_callback(callback: CallbackQuery):
    action = callback.data.split(":")[1]
    
    # Reuse existing logic by calling the handlers or simulating functionality
    # But handlers expect Message, not CallbackQuery. We can't direct call cleanly without adapting.
    # So we adapt.
    
    if action == "buy":
        # Simulate cmd_buy logic
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        for key, pkg in PACKAGES.items():
            btn_text = f"{pkg['name']} ({pkg['nc']} NC) - {pkg['price_rub']}₽"
            if pkg['bonus_percent'] > 0:
                btn_text += f" (+{pkg['bonus_percent']}%)"
            markup.inline_keyboard.append([InlineKeyboardButton(text=btn_text, callback_data=f"buy:{key}")])
        
        # Add Cancel
        markup.inline_keyboard.append([InlineKeyboardButton(text="❌ Я передумал", callback_data="cancel_action")])
        
        await callback.message.answer("💎 **Магазин NeuroCoin**\nВыберите пакет пополнения:", reply_markup=markup, parse_mode="Markdown")
        
    elif action == "upgrade":
        await cmd_upgrade(callback.message) # cmd_upgrade uses message.answer which is fine on callback.message (it's a Message object)
    
    await callback.answer()

# Balance-related CTA callbacks (subscribe/upgrade/coins)
@dp.callback_query(F.data.startswith("balance:"))
async def process_balance_cta(callback: CallbackQuery, state: FSMContext):
    action = callback.data.split(":")[1]
    if action == "subscribe" or action == "upgrade":
        await cmd_upgrade(callback.message)
    elif action == "coins":
        # Переиспользуем магазин NC
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        for key, pkg in PACKAGES.items():
            btn_text = f"{pkg['name']} ({pkg['nc']} NC) - {pkg['price_rub']}₽"
            if pkg['bonus_percent'] > 0:
                btn_text += f" (+{pkg['bonus_percent']}%)"
            markup.inline_keyboard.append([InlineKeyboardButton(text=btn_text, callback_data=f"buy:{key}")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="❌ Я передумал", callback_data="cancel_action")])
        await callback.message.answer("💎 **Магазин NeuroCoin**\nВыберите пакет пополнения:", reply_markup=markup, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "cancel_action")
async def process_cancel_action(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()

@dp.message(Command("buy"))
@dp.message(F.text == "💰 Пополнение")
async def cmd_buy(message: types.Message):
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    for key, pkg in PACKAGES.items():
        btn_text = f"{pkg['name']} ({pkg['nc']} NC) - {pkg['price_rub']}₽"
        if pkg['bonus_percent'] > 0:
            btn_text += f" (+{pkg['bonus_percent']}%)"
        markup.inline_keyboard.append([InlineKeyboardButton(text=btn_text, callback_data=f"buy:{key}")])
        
    # Add Cancel
    markup.inline_keyboard.append([InlineKeyboardButton(text="❌ Я передумал", callback_data="cancel_action")])
        
    # Add fake payment logic handler
    await message.answer("💎 **Магазин NeuroCoin**\nВыберите пакет пополнения:", reply_markup=markup, parse_mode="Markdown")

@dp.callback_query(F.data.startswith("buy:"))
async def process_buy_callback(callback: CallbackQuery):
    pkg_key = callback.data.split(":")[1]
    pkg = PACKAGES.get(pkg_key)
    
    if not pkg:
        await callback.answer("Ошибка пакета")
        return
        
    # MOCK PAYMENT - DISABLED TEMPORARILY
    # user_id = callback.from_user.id
    # new_bal = await update_balance(user_id, pkg['nc'])
    
    await callback.answer("🚧 Оплата временно недоступна. Свяжитесь с админом.", show_alert=True)
    return

    # await callback.message.edit_text(
    #     f"🎉 **Успешная покупка!**\n\n"
    #     f"Вы приобрели пакет **{pkg['name']}**.\n"
    #     f"Начислено: `{pkg['nc']} NC`.\n"
    #     f"Баланс: `{new_bal} NC`.",
    #     parse_mode="Markdown"
    # )
    # await callback.answer()

@dp.message(Command("upgrade"))
@dp.message(F.text == "⬆️ Тарифы")
async def cmd_upgrade(message: types.Message):
    # Show tariffs
    text = (
        "🚀 **Тарифные планы**\n\n"
        "1️⃣ **ДЕМО (0₽)**\n"
        "• 500 NC при старте\n"
        "• Модели: Imagen 4 Fast, Flash, Pro (без 4K)\n"
        "• Разрешения: SD (1K)\n"
        "• AR: только 1:1\n"
        "• Референсы: нет\n"
        "• Диалог: нет\n\n"
        "2️⃣ **БАЗОВЫЙ (390₽/мес)**\n"
        "• Ежемесячно: 3000 NC\n"
        "• Модели: Imagen 4 Fast/Standard/Ultra, Flash, Pro (без 4K)\n"
        "• Разрешения: 1K (Imagen Fast/Std/Ultra), SD (Flash/Pro)\n"
        "• AR: любые\n"
        "• Референсы: до 1\n"
        "• Диалог: нет\n\n"
        "3️⃣ **ПОЛНЫЙ (990₽/мес)**\n"
        "• Ежемесячно: 8000 NC\n"
        "• Модели: все (Imagen Fast/Std/Ultra, Flash, Pro)\n"
        "• Разрешения: 1K/2K (Imagen Std/Ultra), 1024/2K/4K (Pro)\n"
        "• AR: любые\n"
        "• Референсы: до 5\n"
        "• Диалог: да (Pro)\n\n"
        "Админ: полный доступ, расширенные лимиты референсов."
    )
    
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡ Купить БАЗОВЫЙ (390₽)", callback_data="buy_tariff:basic")],
        [InlineKeyboardButton(text="🔥 Купить ПОЛНЫЙ (990₽)", callback_data="buy_tariff:full")],
        [InlineKeyboardButton(text="❌ Закрыть", callback_data="cancel_action")]
    ])
    
    await message.answer(text, parse_mode="Markdown", reply_markup=markup)

@dp.message(Command("buy_tariff"))
async def cmd_buy_tariff_command(message: types.Message):
    # Backward compatibility or manual use
    args = message.text.split()
    if len(args) != 2:
        return
    tariff = args[1].lower()
    await process_tariff_purchase(message.chat.id, tariff, message)

@dp.callback_query(F.data.startswith("buy_tariff:"))
async def process_buy_tariff_callback(callback: CallbackQuery):
    # STUB
    await callback.answer("🚧 Смена тарифа временно недоступна. Пишите админу @dimastro.", show_alert=True)
    return
    
    # tariff = callback.data.split(":")[1]
    # await process_tariff_purchase(callback.message.chat.id, tariff, callback.message)
    # await callback.answer()

async def process_tariff_purchase(user_id: int, tariff: str, message: types.Message):
    if tariff not in ['basic', 'full']:
        return
        
    # STUB - Block all purchase avenues
    await message.answer("🚧 Смена тарифа временно недоступна. Пишите админу @dimastro.", parse_mode="Markdown")
    return

    # Mock Tariff Purchase
    # rules = TARIFFS[tariff]
    # 
    # await set_user_tariff(user_id, tariff)
    # await update_balance(user_id, rules['monthly_nc']) # Give monthly NC
    # 
    # await message.answer(
    #     f"🎉 **Тариф {tariff.upper()} активирован!**\n"
    #     f"Вам начислено {rules['monthly_nc']} NC.\n"
    #     f"Спасибо за поддержку! 🍌",
    url = f"https://DNStrokin.github.io/nano_banana_bot/?level={level}"
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="🍌 Открыть приложение", web_app=WebAppInfo(url=url))],
            [types.KeyboardButton(text="🎨 К созданию")],
            [types.KeyboardButton(text="👤 Мой кабинет"), types.KeyboardButton(text="⬆️ Тарифы")],
            [types.KeyboardButton(text="❓ Помощь")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие"
    )

def get_creation_menu():
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="⚡ Flash"), types.KeyboardButton(text="🍌 Pro")],
            [types.KeyboardButton(text="📸 Imagen")],
            [types.KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите модель"
    )

def get_cancel_menu():
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="❌ Отмена")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )

# --- Command Handlers ---

@dp.message(F.text == "🔙 Назад")
async def cmd_back(message: types.Message, state: FSMContext):
    # Retrieve user for main menu access level
    user = await get_user(message.chat.id)
    level = user.tariff if user else 'demo'
    balance = user.balance if user else None
    await message.answer("🏠 Главное меню", reply_markup=get_main_menu(level, balance))



# Existing handlers...

@dp.message(Command("cancel"))
@dp.message(F.text.lower() == "отмена")
@dp.message(F.text.lower() == "cancel")
@dp.message(F.text == "✅ Завершить диалог")
async def cmd_cancel(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    level = user.tariff if user else 'demo'
    balance = user.balance if user else None

    # Cleanup session
    if message.chat.id in chat_sessions:
        del chat_sessions[message.chat.id]

    current_state = await state.get_state()
    if current_state is None:
        await message.answer("А нечего отменять. Мы на старте.", reply_markup=get_main_menu(level, balance))
        return

    await state.clear()
    await message.answer("🚫 Операция отменена. Возвращаемся в главное меню.", reply_markup=get_main_menu(level, balance))

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
        level = user.tariff if user else 'demo'
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

    # Enforce tariff expiry before access checks
    user = await get_user(message.chat.id)
    user = await enforce_tariff_expiry(user, message)

    # Access Check
    if not await check_access(message.chat.id, model):
        level = user.tariff if user else 'demo'
        balance = user.balance if user else None
        await message.answer(
            f"⛔ Псс, парень! Модель `{model}` тебе недоступна.\n"
            "Постучись админу (или /start для запроса).", 
            reply_markup=get_main_menu(level, balance),
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
    level = user.tariff if user else 'demo'
    balance = user.balance if user else None
    
    help_text = (
        "📚 **Справка по моделям и тарифам**\n\n"
        "🖼 **Imagen 4** (text-to-image)\n"
        "• Fast (`imagen-4.0-fast-generate-001`): AR 1:1/3:4/4:3/9:16/16:9, 1K, без референсов, без диалога, 50 NC\n"
        "• Standard (`imagen-4.0-generate-001`): AR как выше, 1K/2K, без референсов, без диалога, 100 NC\n"
        "• Ultra (`imagen-4.0-ultra-generate-001`): AR как выше, 1K/2K, без референсов, без диалога, 150 NC\n\n"
        "🍌 **Nano Banana (Gemini)**\n"
        "• Flash (`gemini-2.5-flash-image`): AR любые, SD (без 2K/4K), референсы до лимита тарифа, диалог — да, 70 NC\n"
        "• Pro (`gemini-3-pro-image-preview`): AR любые, 1024/2K/4K (лимиты тарифа), референсы до лимита тарифа, диалог — да, 400 NC (+100 за 2K, +350 за 4K)\n\n"
        "💬 Диалог: Flash и Pro.\n"
        "📎 Референсы: Flash и Pro (лимиты тарифа).\n\n"
        "💰 **Тарифы** (RUB/мес, начисление NC):\n"
        "• Demo: 0₽, 500 NC при старте; Imagen Fast, Flash, Pro(без 4K); AR 1:1; refs нет\n"
        "• Basic: 390₽, +3000 NC; Imagen Fast/Std/Ultra, Flash, Pro(без 4K); refs 1; AR любые\n"
        "• Full: 990₽, +8000 NC; все модели; refs 5; 2K/4K для Pro, 1K/2K для Imagen Std/Ultra\n"
        "• Admin: полный доступ\n\n"
        "Курс: 1 RUB = 10 NC. Для генерации списываются NC по моделям выше.\n\n"
        "🎨 **WebApp**: Нажмите 'Открыть приложение', чтобы настроить всё визуально!"
    )
    await message.answer(help_text, parse_mode="Markdown", reply_markup=get_main_menu(level, balance))

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
    user = await enforce_tariff_expiry(user, message)
    # Fallback if no user (shouldn't happen)
    if not user:
        return
        
    tariff = user.tariff
    data = await state.get_data()
    prompt = data.get('prompt', '').strip()
    model = data.get('model')
    refs = data.get('ref_images', []) # List of file_ids
    
    # 1. Validation
    if not prompt: 
        await message.answer("⚠️ Эмм... А рисовать-то что? Напишите хоть пару слов.", reply_markup=get_cancel_menu())
        return # Keep state

    # 3. Parse AR & Res (Pre-validation logic to get final params)
    import re
    ar = data.get('aspect_ratio', '1:1')
    target_res = data.get('resolution', '1024x1024')
    
    # Normalize Imagen resolutions (supports only 1K/2K; fast ignores size)
    if model and "imagen" in model:
        if target_res == "1024x1024":
            target_res = "1K"
        if target_res == "4K":
            target_res = "2K"
    
    # Regex for various dashes: -, --, —, –
    match_ar = re.search(r'(?:--|—|–|-)ar\s+(\d+:\d+)', prompt)
    if match_ar:
        ar = match_ar.group(1)
        prompt = re.sub(r'(?:--|—|–|-)ar\s+\d+:\d+', '', prompt).strip()

    # Regex for resolution
    match_res = re.search(r'(?:--|—|–|-)(1k|2k|4k)', prompt, re.IGNORECASE)
    if match_res:
        requested_res = match_res.group(1).upper()
        prompt = re.sub(r'(?:--|—|–|-)(1k|2k|4k)', '', prompt, flags=re.IGNORECASE).strip()
        target_res = requested_res
    
    # --- PRICING & LIMITS CHECK ---
    
    # Check Limits
    is_valid, reason = validate_request(tariff, model, target_res, len(refs), ar)
    if not is_valid:
        # If invalid, check if we can suggest upgrade
        if "доступна с тарифа БАЗОВЫЙ" in reason:
             msg = f"{reason}\n💡 Апгрейд: `/upgrade`"
        elif "только на тарифе ПОЛНЫЙ" in reason:
             msg = f"{reason}\n💡 Апгрейд: `/upgrade`"
        else:
             msg = reason
        await message.answer(msg, parse_mode="Markdown")
        # Do NOT clear state, let them adjust? Or clear? 
        # Better let them adjust or cancel.
        return 

    # Calculate Cost
    cost = calculate_cost(model, target_res)
    
    # Check Balance
    if user.balance < cost:
        # Подготовка кнопок в зависимости от тарифа
        tariff_lower = user.tariff.lower()
        buttons = []
        if tariff_lower == "demo":
            buttons = [
                InlineKeyboardButton(text="🧾 Оформить подписку", callback_data="balance:subscribe"),
                InlineKeyboardButton(text="💰 Купить монеты", callback_data="balance:coins")
            ]
        elif tariff_lower == "basic":
            buttons = [
                InlineKeyboardButton(text="⬆️ Повысить тариф", callback_data="balance:upgrade"),
                InlineKeyboardButton(text="💰 Купить монеты", callback_data="balance:coins")
            ]
        else:  # full/admin
            buttons = [
                InlineKeyboardButton(text="💰 Купить монеты", callback_data="balance:coins")
            ]
        markup = InlineKeyboardMarkup(inline_keyboard=[buttons])

        await message.answer(
            f"📉 **Недостаточно средств!**\n"
            f"Стоимость: `{cost} NC`\n"
            f"Ваш баланс: `{user.balance} NC`",
            parse_mode="Markdown",
            reply_markup=markup
        )
        return

    # Deduct Balance
    new_balance = await update_balance(user.id, -cost)

    # 4. Status Message
    from aiogram.utils.markdown import hide_link
    ref_info = f"\n📎 Refs: {len(refs)}" if refs else ""
    status_text = (
        f"🍌 **Генерирую...** (`{model}`)\n"
        f"💰 Будет списано: `{cost} NC` (Останется: `{new_balance}`)\n"
        f"📝 `{prompt[:50] + '...' if len(prompt)>50 else prompt}`\n"
        f"📐 AR: `{ar}`"
        f"{ref_info}"
    )
    
    processing_msg = await message.answer(status_text, parse_mode="Markdown")
    
    # Log
    gen_id = await log_generation(message.chat.id, model, prompt, ar, target_res, 'pending')

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
        
        # Add Dialogue Ref if exists
        dialogue_ref = data.get('dialogue_ref_file_id')
        if dialogue_ref and dialogue_ref not in refs:
             refs.append(dialogue_ref)

        if refs:
            bot_instance = message.bot
            for file_id in refs:
                file = await bot_instance.get_file(file_id)
                io_bytes = await bot_instance.download_file(file.file_path)
                image_bytes_list.append(io_bytes.read())

        # Call API
        # Retrieve existing chat session if in dialogue mode
        chat_session = None
        is_continuation = data.get('is_dialogue_continuation', False)
        
        if is_continuation:
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
        # token_text removed by user request
        
        # Truncate prompt for caption (safety limit)
        display_prompt = prompt[:900] + "..." if len(prompt) > 900 else prompt
        # Escape backticks to prevent markdown breakage
        display_prompt = display_prompt.replace("`", "'")

        final_caption = (
            f"✨ Готово! *{model_display}*\n"
            f"💸 Списано: {cost} NC | 💼 Баланс: {new_balance} NC\n\n"
            f"📌 *Промпт:*\n"
            f"```\n{display_prompt}\n```\n"
            f"🍌 @dimastro\_banana\_bot"
        )

        # Logic for Dialogue continuation
        # DEFAULT: Minimal menu + Inline Result Actions
        reply_keyboard = get_minimal_menu()
        
        # Prepare Callback Data (Safe Encoding)
        ar_safe = ar.replace(':', '_')
        res_clean = target_res # e.g. 1024x1024 or 4K. Should be safe.
        
        # Check if dialogue is supported
        model_meta = MODEL_DISPLAY.get(model, {})
        supports_dialogue = model_meta.get("supports_dialogue", False)

        # Inline Result Actions
        result_inline_rows = [
            [
                InlineKeyboardButton(text="🔄 Создать ещё", callback_data=f"create:again:{model}:{ar_safe}:{res_clean}"),
                InlineKeyboardButton(text="⬅️ К другой модели", callback_data="create:back:start")
            ]
        ]
        # Добавим кнопку завершения диалога (inline), чтобы не засорять reply-клавиатуру
        if supports_dialogue:
            result_inline_rows.append([InlineKeyboardButton(text="❌ Завершить диалог", callback_data="dialogue:finish")])
        result_inline = InlineKeyboardMarkup(inline_keyboard=result_inline_rows)

        if supports_dialogue:
             # Включаем режим ожидания диалога для всех, даже для демо, чтобы ловить их сообщения
             await state.set_state(GenStates.dialogue_standby)
             if tariff != 'demo':
                 logging.info(f"DIALOGUE: Activated for model {model}, tariff {tariff}")
             else:
                 # Демо: диалог недоступен, но оставляем минимальную клавиатуру и очищаем чат-сессию
                 if message.chat.id in chat_sessions:
                     del chat_sessions[message.chat.id]
                 logging.info(f"DIALOGUE: Demo user, showing upgrade prompt on next message.")
        else:
             logging.info(f"DIALOGUE: NOT activated for model {model}, tariff {tariff}, supports_dialogue={supports_dialogue}")
             await state.clear()
             # Clear session if not continuing
             if message.chat.id in chat_sessions:
                 del chat_sessions[message.chat.id]
        
        # Send Result (attach minimal reply keyboard here to avoid extra text message)
        photo = BufferedInputFile(image_bytes, filename=f"banana_{model}.png")
        await message.answer_photo(
             photo,
             caption=final_caption,
             parse_mode="Markdown",
             reply_markup=reply_keyboard
        )

        # Send inline buttons and update reply keyboard
        actions_msg = await message.answer("Выберите действие:", reply_markup=result_inline)

        # Обновить реплай-клавиатуру: диалоговая или минимальная (чтобы убрать главное меню)
        if supports_dialogue:
            dlg_msg = await message.answer("💬 Режим диалога", reply_markup=reply_keyboard)
            # Сохраняем ID сообщения с индикатором диалога, чтобы можно было удалить при завершении
            await state.update_data(dialogue_indicator_msg_id=dlg_msg.message_id, actions_msg_id=actions_msg.message_id)


        
        # Cleanup
        try:
            await processing_msg.delete()
        except:
            pass
            
        # Delete Config Message (Menu)
        config_msg_id = data.get("config_message_id")
        if config_msg_id:
             try:
                 await message.bot.delete_message(chat_id=message.chat.id, message_id=config_msg_id)
             except:
                 pass

    except Exception as e:
        # REFUND
        refund_bal = await update_balance(user.id, cost)
        await update_generation_status(gen_id, 'failed')
        
        await message.answer(
            f"❌ Упс! Ошибка генерации: {e}\n"
            f"💰 **Средства возвращены.** Баланс: {refund_bal} NC", 
            reply_markup=get_main_menu(tariff, refund_bal)
        )
        if message.chat.id in chat_sessions:
            del chat_sessions[message.chat.id]
    
# In-memory session storage (simple approach for single instance bot)
chat_sessions = {}

class GenStates(StatesGroup):
    waiting_for_prompt = State()
    dialogue = State()
    dialogue_standby = State()
    dialogue_confirm = State()

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



@dp.message(Command("help"))
@dp.message(F.text == "❓ Помощь")
async def cmd_help(message: types.Message):
    text = (
        "🍌 **Nano Banana Bot Help**\n\n"
        "**Режимы:**\n"
        "⚡ **Flash**: Быстро, бесплатно (Demo), для тестов.\n"
        "🍌 **Pro**: Умный режим, высокое качество, диалог.\n"
        "📸 **Imagen**: Фотореализм (только генерация).\n\n"
        "**Валюта (NC):**\n"
        "Используется для оплаты генераций. Баланс пополняется покупкой пакетов или подпиской.\n\n"
        "**Команды в чате:**\n"
        "--ar X:Y (например --ar 16:9) - Соотношение сторон\n"
        "--4k - Повышенное разрешение (для Full)\n\n"
        "**Поддержка:** @admin_handle"
    )
    await message.answer(text, parse_mode="Markdown")

# --- Creation Flow ---
class CreationStates(StatesGroup):
    choosing_mode = State()
    choosing_family = State()
    choosing_model = State()
    configuring = State()
    waiting_for_prompt = State()

async def show_creation_start(message: types.Message, user: User, is_edit=False):
    text = (
        f"🎨 **Мастерская Nano Banana**\n\n"
        f"👤 Тариф: **{user.tariff.upper()}**\n"
        f"💰 Баланс: **{user.balance} NC**\n\n"
        f"Что будем создавать?"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🖼 Создать изображение", callback_data="create:mode:image")],
        [InlineKeyboardButton(text="🎥 Создать видео (Beta)", callback_data="create:mode:video")]
    ])
    if is_edit:
        await message.edit_text(text, parse_mode="Markdown", reply_markup=markup)
    else:
        await message.answer(text, parse_mode="Markdown", reply_markup=markup)


@dp.message(GenStates.dialogue_standby)
async def process_dialogue_standby(message: types.Message, state: FSMContext):
    logging.info(f"DIALOGUE: process_dialogue_standby triggered for user {message.from_user.id}")

    # 1. Capture Input
    dialogue_text = message.text or message.caption
    ref_image = None

    if message.photo:
         ref_image = message.photo[-1] # ID
         if not dialogue_text:
             dialogue_text = "" # Allow empty prompt if image

    if not dialogue_text and not ref_image:
        await message.answer("⚠️ Пришлите текст или фото для продолжения диалога.")
        return

    # Check Navigation/Cancel commands explicitly
    if dialogue_text and (dialogue_text == "🏠 Главное меню" or dialogue_text == "✅ Завершить диалог" or dialogue_text.lower() in ["/start", "cancel", "отмена"]):
         await cmd_cancel(message, state) # Handled by cancel
         return

    # 2. Check Tariff
    user = await get_user(message.from_user.id)
    if user.tariff == 'demo' and user.access_level != 'admin':
         # Show upgrade message with inline buttons
         confirm_markup = InlineKeyboardMarkup(inline_keyboard=[
             [InlineKeyboardButton(text="💎 Сменить тариф", callback_data="dialogue:upgrade")],
             [InlineKeyboardButton(text="❌ Отказаться", callback_data="dialogue:cancel")]
         ])

         confirm_msg = await message.answer(
             "🔒 **Режим диалога доступен только на тарифе ПОЛНЫЙ**\n\n"
             "Перейдите на тариф ПОЛНЫЙ, чтобы продолжить диалог с моделью.",
             reply_markup=confirm_markup
         )

         # Store message IDs for cleanup
         await state.update_data(
             user_message_id=message.message_id,
             confirm_message_id=confirm_msg.message_id,
             dialogue_text=dialogue_text,
             dialogue_ref_file_id=ref_image.file_id if ref_image else None
         )
         return

    # 3. Save Context and show confirmation
    data = await state.get_data()
    model = data.get("model", "gemini-3-pro-image-preview")
    # Use same pricing logic as основной триггер, включая надбавки за разрешение
    resolution = data.get("resolution", "1024x1024")
    cost = calculate_cost(model, resolution)

    # Show confirmation message with inline buttons
    confirm_markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отправить", callback_data="dialogue:confirm")],
        [InlineKeyboardButton(text="❌ Завершить", callback_data="dialogue:cancel")]
    ])

    confirm_msg = await message.answer(
        f"💬 **Подтверждение диалога**\n\n"
        f"Диалог с моделью будет продолжен.\n"
        f"💰 Будет списано: **{cost} NC**\n"
        f"💼 Ваш баланс: **{user.balance} NC**\n\n"
        f"Отправить сообщение модели?",
        reply_markup=confirm_markup
    )

    # Store data for confirmation
    await state.update_data(
        user_message_id=message.message_id,
        confirm_message_id=confirm_msg.message_id,
        dialogue_text=dialogue_text,
        dialogue_ref_file_id=ref_image.file_id if ref_image else None
    )
    await state.set_state(GenStates.dialogue_confirm)

@dp.callback_query(F.data.startswith("dialogue:"))
async def process_dialogue_confirm_callback(callback: CallbackQuery, state: FSMContext):
    action = callback.data.split(":")[1]
    data = await state.get_data()

    async def finish_dialog():
        # Clear FSM and chat session
        await state.clear()
        if callback.message.chat.id in chat_sessions:
            del chat_sessions[callback.message.chat.id]
        # Temp notification
        finish_msg = await callback.message.answer("✅ Диалог завершен.")
        asyncio.create_task(delete_message_delayed(finish_msg, 3))
        # Удаляем индикатор "Режим диалога", если есть
        indicator_id = data.get("dialogue_indicator_msg_id")
        if indicator_id:
            try:
                await callback.bot.delete_message(callback.message.chat.id, indicator_id)
            except:
                pass
        # Правим inline-кнопки у сообщения действий: оставляем только "Создать ещё" и "К другой модели"
        actions_msg_id = data.get("actions_msg_id")
        if actions_msg_id:
            try:
                ar_safe = data.get("aspect_ratio", "1:1").replace(":", "_")
                res_clean = data.get("resolution", "1024x1024")
                model = data.get("model", "nano_banana")
                cleaned_markup = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="🔄 Создать ещё", callback_data=f"create:again:{model}:{ar_safe}:{res_clean}"),
                    InlineKeyboardButton(text="⬅️ К другой модели", callback_data="create:back:start")
                ]])
                await callback.bot.edit_message_reply_markup(chat_id=callback.message.chat.id, message_id=actions_msg_id, reply_markup=cleaned_markup)
            except:
                pass

    if action == "upgrade":
        # Send user to tariff upgrade
        await callback.message.delete()
        # Delete user's original message too
        user_msg_id = data.get("user_message_id")
        if user_msg_id:
            try:
                await callback.bot.delete_message(callback.message.chat.id, user_msg_id)
            except:
                pass
        await state.clear()
        await cmd_upgrade(callback.message)
        await callback.answer()

    elif action == "cancel":
        # Cancel dialogue - delete messages
        try:
            await callback.message.delete()
        except:
            pass
        user_msg_id = data.get("user_message_id")
        if user_msg_id:
            try:
                await callback.bot.delete_message(callback.message.chat.id, user_msg_id)
            except:
                pass
        await finish_dialog()
        await callback.answer()

    elif action == "confirm":
        # Proceed with dialogue generation
        await callback.message.delete() # Delete confirm prompt
        processing_msg = await callback.message.answer("⏳ Генерирую ответ...")

        # Update state with dialogue data
        await state.update_data(
            prompt=data.get("dialogue_text"),
            dialogue_ref_file_id=data.get("dialogue_ref_file_id"),
            is_dialogue_continuation=True
        )

        # Удаляем действия/индикаторы, чтобы не нажимали во время новой генерации
        actions_msg_id = data.get("actions_msg_id")
        if actions_msg_id:
            try:
                await callback.bot.delete_message(callback.message.chat.id, actions_msg_id)
            except:
                pass
            await state.update_data(actions_msg_id=None)
        indicator_id = data.get("dialogue_indicator_msg_id")
        if indicator_id:
            try:
                await callback.bot.delete_message(callback.message.chat.id, indicator_id)
            except:
                pass
            await state.update_data(dialogue_indicator_msg_id=None)

        # Call trigger logic
        await trigger_generation(callback.message, state)
        await callback.answer()

        # Clean up processing message
        try:
            await processing_msg.delete()
        except:
            pass
    elif action == "finish":
        await finish_dialog()
        await callback.answer()

@dp.message(F.text == "🎨 К созданию")

async def cmd_creation_entry(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    # Update Reply Keyboard (Minimal)
    workshop_msg = await message.answer("🎨 **Мастерская**", reply_markup=get_minimal_menu())
    # Запомним ID, чтобы потом удалить при старте генерации
    await state.update_data(workshop_message_id=workshop_msg.message_id)
    # Show Inline UI
    await show_creation_start(message, user)

@dp.callback_query(F.data.startswith("create:"))
async def process_create_callback(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    action = parts[1] # mode, family, model, config, prompt_form
    value = parts[2] if len(parts) > 2 else None
    
    user = await get_user(callback.from_user.id)
    
    if action == "mode":
        if value == "video":
            await callback.answer("Видео пока в разработке! 🚧", show_alert=True)
            return
        
        # Show Families
        text = "🤖 **Выберите тип модели:**\n\n" \
               "🍌 **Nano Banana** — умные модели от Google (Gemini)\n" \
               "📸 **Imagen** — фотореализм от Google"
               
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🍌 Nano Banana", callback_data="create:family:banana")],
            [InlineKeyboardButton(text="📸 Imagen", callback_data="create:family:imagen")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="create:back:start")]
        ])
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=markup)
        
    elif action == "family":
        family = value
        # Show specific models filtered by family
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        
        for mid, meta in MODEL_DISPLAY.items():
            if meta['family'] != family:
                continue
                
            price = MODEL_PRICES.get(mid, 0)
            btn_text = f"{meta['name']} — {price} NC"
            markup.inline_keyboard.append([InlineKeyboardButton(text=btn_text, callback_data=f"create:model:{mid}")])
            
        markup.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="create:mode:image")])
        
        await callback.message.edit_text("🧠 **Выберите модель:**", parse_mode="Markdown", reply_markup=markup)
        
    elif action == "model":
        model_id = value
        # Set model in state
        await state.update_data(model=model_id)
        # Default config if not set
        data = await state.get_data()
        meta = MODEL_DISPLAY.get(model_id, {})
        if not data.get("aspect_ratio"):
            await state.update_data(aspect_ratio="1:1")
        if not data.get("resolution"):
             default_res = "1K" if meta.get("family") == "imagen" else "1024x1024"
             await state.update_data(resolution=default_res)
        
        await show_config_menu(callback.message, state, user)
        
    elif action == "config":
        # create:config:ar:16:9
        # create:config:res:4K
        sub_action = parts[2]
        
        if sub_action == "ar":
            val = parts[3] + ":" + parts[4] if len(parts) > 4 else parts[3]
            await state.update_data(aspect_ratio=val)
        elif sub_action == "res":
             val = parts[3]
             # Check access
             user_tariff_rules = TARIFFS.get(user.tariff, TARIFFS['demo'])
             can_high_res = user_tariff_rules.get('can_use_2k_4k', False)
             
             if val in ["2K", "4K"] and not can_high_res and user.tariff != 'admin':
                 await callback.answer(
                     f"🔒 Разрешение {val} доступно только на тарифе FULL.\n"
                     "Используйте /upgrade для перехода.", 
                     show_alert=True
                 )
                 return
             
             await state.update_data(resolution=val)
             
        await show_config_menu(callback.message, state, user)

    elif action == "again":
         # create:again:model:ar_safe:res
         # e.g. create:again:nano_banana:16_9:1024x1024
         # Убираем индикатор диалога, если он был
         data = await state.get_data()
         indicator_id = data.get("dialogue_indicator_msg_id")
         if indicator_id:
             try:
                 await callback.bot.delete_message(callback.message.chat.id, indicator_id)
             except:
                 pass
             await state.update_data(dialogue_indicator_msg_id=None)
         # actions_msg сохранять не нужно, оно будет перезаписано после новой генерации
         if len(parts) >= 5:
             model_id = parts[2]
             ar_safe = parts[3]
             res = parts[4]
             
             ar = ar_safe.replace('_', ':')
             
             await state.update_data(model=model_id, aspect_ratio=ar, resolution=res)
             await show_config_menu(callback.message, state, user)
         else:
             # Fallback if somehow empty
             await callback.answer("Ошибка данных повтора.", show_alert=True)

    elif action == "back":
        if value == "start":
             # If message is photo (result), cannot edit_text -> send new
             # If text (menu), edit it
             can_edit = (callback.message.content_type == "text")
             # Удаляем индикатор диалога при возврате
             data = await state.get_data()
             indicator_id = data.get("dialogue_indicator_msg_id")
             if indicator_id:
                 try:
                     await callback.bot.delete_message(callback.message.chat.id, indicator_id)
                 except:
                     pass
                 await state.update_data(dialogue_indicator_msg_id=None)
             await show_creation_start(callback.message, user, is_edit=can_edit)
    
    await callback.answer()

async def show_config_menu(message: types.Message, state: FSMContext, user: User):
    # Set state immediately so user can type
    await state.set_state(CreationStates.waiting_for_prompt)
    
    data = await state.get_data()
    model = data.get("model")
    ar = data.get("aspect_ratio", "1:1")
    res = data.get("resolution", "1024x1024")
    
    meta = MODEL_DISPLAY.get(model, {})
    price_base = MODEL_PRICES.get(model, 0)
    supports_res = meta.get("supports_resolution", False)
    supports_refs = meta.get("supports_references", False)
    supports_dialogue = meta.get("supports_dialogue", False)

    # Calculate Cost
    surcharge = 0
    if supports_res and res in RESOLUTION_SURCHARGES:
        surcharge = RESOLUTION_SURCHARGES.get(res, 0)
        
    total_cost = price_base + surcharge
    
    # Build Text
    text = (
        f"⚙️ **Настройка генерации**\n\n"
        f"🧠 Модель: **{meta.get('name', model)}**\n"
        f"📐 AR: **{ar}**\n"
    )
    
    if supports_res:
        text += f"🔍 Качество: **{res}**\n"
    
    text += f"\n💰 Стоимость: **{total_cost} NC**\n"

    if supports_dialogue:
        text += "💬 **Поддерживает режим диалога**\n"

    text += "\n✏️ **Введите промпт:**\nПросто напишите, что хотите увидеть.\n"

    # Build markup
    markup = InlineKeyboardMarkup(inline_keyboard=[])

    # AR Row (Aspect Ratio)
    ar_row = []
    # AR options: для Imagen ограничиваемся допустимыми
    imagen_ar_options = ["1:1", "3:4", "4:3", "9:16", "16:9"]
    ar_options = imagen_ar_options if meta.get('family') == 'imagen' else ["1:1", "16:9", "9:16", "4:3", "3:4", "21:9", "9:21"]
    for ratio in ar_options:
        label = ratio
        if ratio == ar:
            label = f"✅ {ratio}"
        ar_row.append(InlineKeyboardButton(text=label, callback_data=f"create:config:ar:{ratio}"))
    markup.inline_keyboard.append(ar_row)

    # Res Row (Only if supported)
    if supports_res:
        res_row = []
        # Для Imagen используем 1K/2K; для остальных — прежние
        options = ["1K", "2K"] if meta.get('family') == 'imagen' else ["1024x1024", "2K", "4K"]
        
        user_tariff_rules = TARIFFS.get(user.tariff, TARIFFS['demo'])
        can_high_res = user_tariff_rules.get('can_use_2k_4k', False)
        
        for opt in options:
            opt_label = "SD" if opt in ["1024x1024", "1K"] else opt
            if opt in RESOLUTION_SURCHARGES:
                 opt_label += f" (+{RESOLUTION_SURCHARGES[opt]} NC)"
            
            is_locked = False
            if opt in ["2K", "4K"] and not can_high_res and user.tariff != 'admin':
                is_locked = True
                
            if is_locked:
                 opt_label = f"🔒 {opt_label}"
            
            if opt == res and not is_locked:
                opt_label = f"✅ {opt_label}"
            
            res_row.append(InlineKeyboardButton(text=opt_label, callback_data=f"create:config:res:{opt}"))
        markup.inline_keyboard.append(res_row)
    
    # No "Enter Prompt" button anymore!
    meta_fam = meta.get('family', 'banana')
    markup.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад к списку", callback_data=f"create:family:{meta_fam}")])
    
    try:
        await message.edit_text(text, parse_mode="Markdown", reply_markup=markup)
        msg_id = message.message_id
    except:
        new_msg = await message.answer(text, parse_mode="Markdown", reply_markup=markup)
        msg_id = new_msg.message_id
        
    # Save ID for later deletion
    await state.update_data(config_message_id=msg_id)

def get_main_menu(tariff: str, balance: int | None = None):
    profile_label = "👤 Мой кабинет"
    if balance is not None:
        profile_label += f" ({balance} NC)"
    tariff_label = "💎 Тарифы"
    if tariff:
        tariff_label += f" ({tariff.upper()})"
    kb = [
        [KeyboardButton(text="🎨 К созданию")],
        [KeyboardButton(text=profile_label), KeyboardButton(text=tariff_label)],
        [KeyboardButton(text="❓ Помощь")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, one_time_keyboard=True)

def get_minimal_menu():
    """Returns a minimal reply keyboard with just 'Main Menu'."""
    kb = [
        [KeyboardButton(text="🏠 Главное меню")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, one_time_keyboard=True)


@dp.message(CreationStates.waiting_for_prompt)
async def process_creation_prompt(message: types.Message, state: FSMContext):
    # Capture prompt
    text = message.text or message.caption
    
    # Check for Navigation / Cancel
    if text and (text == "🏠 Главное меню" or text.lower() in ["/start", "отмена", "cancel"]):
         # Reset flow
         await state.clear()
         # Delete the config message to be clean?
         data = await state.get_data()
         config_msg_id = data.get("config_message_id")
         if config_msg_id:
             try:
                 await message.bot.delete_message(message.chat.id, config_msg_id)
             except:
                 pass
         
         # Redirect to Start (Main Menu)
         user = await get_user(message.from_user.id)
         await message.answer("🏠 **Главное меню**", reply_markup=get_main_menu(user.tariff, user.balance if user else None))
         return

    if not text and not message.photo:
         await message.answer("⚠️ Пришлите текст или фото.")
         return
         
    await state.update_data(prompt=text)
    
    if message.photo:
         refs = []
         refs.append(message.photo[-1].file_id)
         await state.update_data(ref_images=refs)
    
    # Убираем меню конфигурации с кнопкой "Назад", чтобы в ожидании не вернуться к выбору модели
    data = await state.get_data()
    config_msg_id = data.get("config_message_id")
    if config_msg_id:
         try:
             await message.bot.delete_message(chat_id=message.chat.id, message_id=config_msg_id)
         except:
             pass
         await state.update_data(config_message_id=None)
    
    # Удаляем сообщение "Мастерская", чтобы не засоряло диалог
    workshop_msg_id = data.get("workshop_message_id")
    if workshop_msg_id:
         try:
             await message.bot.delete_message(chat_id=message.chat.id, message_id=workshop_msg_id)
         except:
             pass
         await state.update_data(workshop_message_id=None)
    
    # Generate!
    # trigger_generation сам устанавливает нужное состояние (dialogue_standby или очищает),
    # поэтому не трогаем состояние здесь, чтобы не сломать диалог.
    await trigger_generation(message, state)


@dp.message(F.text == "🏠 Главное меню")
async def cmd_main_menu_text(message: types.Message, state: FSMContext):
    await state.clear()
    # Удаляем индикатор диалога, если был
    data = await state.get_data()
    indicator_id = data.get("dialogue_indicator_msg_id")
    if indicator_id:
        try:
            await message.bot.delete_message(message.chat.id, indicator_id)
        except:
            pass
        await state.update_data(dialogue_indicator_msg_id=None)
    await cmd_start(message)

@dp.message(F.text.startswith("👤 Мой кабинет"))
async def cmd_profile_text(message: types.Message):
    await cmd_profile(message)

@dp.message(F.text.startswith("💎 Тарифы"))
async def cmd_tariffs_text(message: types.Message):
    await cmd_upgrade(message)

@dp.message(F.text)
async def handle_unknown_text(message: types.Message, state: FSMContext):
    # This triggers if no other handler caught it (e.g. not a command, not in FSM state)
    current_state = await state.get_state()
    logging.info(f"UNKNOWN: handle_unknown_text triggered. State: {current_state}, User: {message.from_user.id}")

    # Don't handle messages that are in dialogue states
    if current_state and current_state.startswith('GenStates:'):
        logging.info(f"UNKNOWN: Ignoring message in state {current_state}")
        return

    user = await get_user(message.chat.id)
    level = user.tariff if user else 'demo'
    balance = user.balance if user else None

    msg = (
        "🤖 **Я вас не понял.**\n"
        "Сейчас мы не в режиме генерации или диалога.\n\n"
        "🔹 **Хотите рисовать?** Выберите режим в меню (Flash/Pro/Imagen).\n"
        "🔹 **Хотите поговорить?** Диалог поддерживается **только** в режиме `/pro` (для Full/Admin). В режимах Flash/Imagen диалог после генерации не работает.\n\n"
        "Для новой генерации нажмите одну из кнопок ниже 👇"
    )
    await message.answer(msg, reply_markup=get_main_menu(level, balance), parse_mode="Markdown")

async def main():
    logging.info("Starting bot...")
    
    # Set bot commands menu
    commands = [
        types.BotCommand(command="start", description="Запустить бота"),
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
